#[cfg(target_os = "linux")]
mod linux_seccomp {
    use crate::error::{LinuxSubstrateError, Result};
    use crate::types::SeccompProfile;
    use seccompiler::{SeccompAction, SeccompFilter, SeccompRule, SeccompCondition, TargetArch, sock_filter, apply_filter};
    use std::collections::{BTreeMap, HashSet};
    use std::os::unix::io::AsRawFd;

    /// Seccomp filter rules for default profile
    const DEFAULT_ALLOWED_SYSCALLS: &[i64] = &[
        // Process management
        libc::SYS_read, libc::SYS_write, libc::SYS_open, libc::SYS_close,
        libc::SYS_fstat, libc::SYS_lseek, libc::SYS_mmap, libc::SYS_munmap,
        libc::SYS_brk, libc::SYS_rt_sigaction, libc::SYS_rt_sigprocmask,
        libc::SYS_rt_sigreturn, libc::SYS_exit, libc::SYS_exit_group,
        libc::SYS_getpid, libc::SYS_getppid, libc::SYS_getuid, libc::SYS_getgid,
        libc::SYS_geteuid, libc::SYS_getegid, libc::SYS_gettid,
        
        // File operations
        libc::SYS_openat, libc::SYS_read, libc::SYS_write, libc::SYS_close,
        libc::SYS_fstat, libc::SYS_lstat, libc::SYS_statx,
        libc::SYS_fcntl, libc::SYS_ioctl, libc::SYS_pread64, libc::SYS_pwrite64,
        libc::SYS_ftruncate, libc::SYS_fsync, libc::SYS_fdatasync,
        libc::SYS_mkdirat, libc::SYS_unlinkat, libc::SYS_renameat,
        libc::SYS_linkat, libc::SYS_symlinkat, libc::SYS_readlinkat,
        
        // Process management
        libc::SYS_fork, libc::SYS_vfork, libc::SYS_clone, libc::SYS_execve,
        libc::SYS_wait4, libc::SYS_waitid, libc::SYS_kill, libc::SYS_tkill,
        
        // Memory
        libc::SYS_mmap, libc::SYS_munmap, libc::SYS_mprotect, libc::SYS_madvise,
        libc::SYS_brk, libc::SYS_mremap,
        
        // Time
        libc::SYS_clock_gettime, libc::SYS_nanosleep, libc::SYS_gettimeofday,
        libc::SYS_time,
        
        // Network (if allowed)
        libc::SYS_socket, libc::SYS_connect, libc::SYS_accept, libc::SYS_bind,
        libc::SYS_listen, libc::SYS_sendto, libc::SYS_recvfrom, libc::SYS_sendmsg,
        libc::SYS_recvmsg, libc::SYS_shutdown, libc::SYS_getsockopt, libc::SYS_setsockopt,
        
        // Futex
        libc::SYS_futex,
        
        // Epoll
        libc::SYS_epoll_create1, libc::SYS_epoll_ctl, libc::SYS_epoll_pwait,
        
        // Signal
        libc::SYS_rt_sigaction, libc::SYS_rt_sigprocmask, libc::SYS_rt_sigpending,
        libc::SYS_rt_sigtimedwait, libc::SYS_sigaltstack,
        
        // Other
        libc::SYS_getrandom, libc::SYS_getcpu, libc::SYS_sched_yield,
        libc::SYS_sched_getaffinity, libc::SYS_sched_setaffinity,
        libc::SYS_set_robust_list, libc::SYS_get_robust_list,
        libc::SYS_prlimit64, libc::SYS_getrlimit, libc::SYS_setrlimit,
        libc::SYS_getrusage, libc::SYS_sysinfo,
    ];

    /// Strict profile - minimal syscalls
    const STRICT_SYSCALLS: &[i64] = &[
        libc::SYS_read, libc::SYS_write, libc::SYS_open, libc::SYS_close,
        libc::SYS_exit, libc::SYS_exit_group, libc::SYS_read, libc::SYS_write,
    ];

    /// Build seccomp filter for given profile (returns raw sock_filter bytes)
    pub fn build_seccomp_filter(profile: SeccompProfile) -> Result<Vec<seccompiler::sock_filter>> {
        let allowed_syscalls = match profile {
            SeccompProfile::Default => DEFAULT_ALLOWED_SYSCALLS,
            SeccompProfile::Strict => STRICT_SYSCALLS,
            SeccompProfile::Custom(_) => DEFAULT_ALLOWED_SYSCALLS, // TODO: parse custom
        };

        // Build rules map: syscall_number -> vec of rules
        let mut rules: BTreeMap<i64, Vec<SeccompRule>> = BTreeMap::new();
        
        for &syscall in allowed_syscalls {
            let condition = SeccompCondition::Eq(syscall as u32);
            let rule = SeccompRule::new(vec![condition]).unwrap();
            rules.entry(syscall).or_default().push(rule);
        }
        
        // Deny all others with EPERM
        let default_action = SeccompAction::Errno(libc::EPERM as u32);
        
        // Build filter with seccompiler 0.5 API
        let filter = SeccompFilter::new(
            rules,
            default_action,
            SeccompAction::Allow, // action for matches
            TargetArch::x86_64,
        ).map_err(|e| LinuxSubstrateError::Seccomp(e.to_string()))?;
        
        // Convert to BPF program (returns Vec<sock_filter>)
        let program = filter.try_into()
            .map_err(|e| LinuxSubstrateError::Seccomp(e.to_string()))?;
        
        Ok(program)
    }
    
    /// Apply seccomp filter to current process
    pub fn apply_seccomp_filter(profile: SeccompProfile) -> Result<()> {
        let program = build_seccomp_filter(profile)?;
        
        // Use seccompiler's helper to apply the filter
        seccompiler::apply_filter(&program[..])
            .map_err(|e| LinuxSubstrateError::Seccomp(e.to_string()))?;
        
        Ok(())
    }
    
    /// Install seccomp filter for a child process (called after fork, before exec)
    pub fn install_seccomp_for_child(profile: SeccompProfile) -> Result<()> {
        apply_seccomp_filter(profile)
    }
    
    /// Get list of allowed syscalls for a profile
    pub fn get_allowed_syscalls(profile: SeccompProfile) -> HashSet<i64> {
        let allowed_syscalls = match profile {
            SeccompProfile::Default => DEFAULT_ALLOWED_SYSCALLS,
            SeccompProfile::Strict => STRICT_SYSCALLS,
            SeccompProfile::Custom(_) => DEFAULT_ALLOWED_SYSCALLS, // TODO: parse custom
        };
        allowed_syscalls.iter().copied().collect()
    }
}

/// Re-export the Linux seccomp functions
#[cfg(target_os = "linux")]
pub use linux_seccomp::*;

/// Stub implementations for non-Linux platforms
#[cfg(not(target_os = "linux"))]
mod stub_seccomp {
    use crate::error::{LinuxSubstrateError, Result};
    use crate::types::SeccompProfile;
    use std::collections::HashSet;
    
    pub fn build_seccomp_filter(_profile: SeccompProfile) -> Result<Vec<seccompiler::sock_filter>> {
        Err(LinuxSubstrateError::Unavailable("Seccomp not supported on this platform".to_string()))
    }
    
    pub fn apply_seccomp_filter(_profile: SeccompProfile) -> Result<()> {
        Err(LinuxSubstrateError::Unavailable("Seccomp not supported on this platform".to_string()))
    }
    
    pub fn install_seccomp_for_child(_profile: SeccompProfile) -> Result<()> {
        Err(LinuxSubstrateError::Unavailable("Seccomp not supported on this platform".to_string()))
    }
    
    pub fn get_allowed_syscalls(_profile: SeccompProfile) -> HashSet<i64> {
        HashSet::new()
    }
}

/// Re-export the stub functions for non-Linux platforms
#[cfg(not(target_os = "linux"))]
pub use stub_seccomp::*;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_syscalls_not_empty() {
        #[cfg(target_os = "linux")]
        {
            assert!(!super::linux_seccomp::DEFAULT_ALLOWED_SYSCALLS.is_empty());
        }
    }
    
    #[test]
    fn test_strict_smaller_than_default() {
        #[cfg(target_os = "linux")]
        {
            assert!(super::linux_seccomp::STRICT_SYSCALLS.len() < super::linux_seccomp::DEFAULT_ALLOWED_SYSCALLS.len());
        }
    }
}