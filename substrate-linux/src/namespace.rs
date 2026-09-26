#[cfg(target_os = "linux")]
mod linux_namespace {
    use crate::error::{LinuxSubstrateError, Result};
    use nix::sched::{clone, CloneFlags};
    use nix::unistd::{fork, ForkResult, Gid, Uid, setgid, setuid, chdir};
    use nix::mount::{mount, umount, MsFlags};
    use std::ffi::CString;
    use std::os::unix::process::CommandExt;
    use std::process::Command;
    use std::os::unix::io::AsRawFd;
    use std::fs;
    use std::path::Path;
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::process::CommandExt as UnixCommandExt;
    use std::process::Stdio;
    use std::ptr;
    use std::mem;
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::Arc;

    /// Namespace flags for clone()
    const CLONE_NEWUSER: i32 = 0x10000000;
    const CLONE_NEWNS: i32 = 0x00020000;
    const CLONE_NEWPID: i32 = 0x00000200;
    const CLONE_NEWNET: i32 = 0x40000000;
    const CLONE_NEWUTS: i32 = 0x04000000;
    const CLONE_NEWIPC: i32 = 0x08000000;
    const CLONE_NEWCGROUP: i32 = 0x02000000;

    /// Configuration for namespace setup
    #[derive(Debug, Clone)]
    pub struct NamespaceConfig {
        pub enable_user: bool,
        pub enable_mount: bool,
        pub enable_pid: bool,
        pub enable_network: bool,
        pub enable_uts: bool,
        pub enable_ipc: bool,
        pub enable_cgroup: bool,
        pub uid_map: Vec<(u32, u32, u32)>, // (inside_uid, outside_uid, count)
        pub gid_map: Vec<(u32, u32, u32)>,
        pub mount_propagation: MountPropagation,
    }

    #[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
    pub enum MountPropagation {
        #[default]
        Private,
        Slave,
        Shared,
        Unchanged,
    }

    impl Default for NamespaceConfig {
        fn default() -> Self {
            Self {
                enable_user: true,
                enable_mount: true,
                enable_pid: true,
                enable_network: false,
                enable_uts: true,
                enable_ipc: true,
                enable_cgroup: false,
                uid_map: vec![(0, 0, 1)], // Map root to current user
                gid_map: vec![(0, 0, 1)],
                mount_propagation: MountPropagation::Private,
            }
        }
    }

    /// RAII guard for namespace cleanup
    pub struct NamespaceGuard {
        original_ns: Vec<(String, std::fs::File)>,
        cleanup_mount: bool,
    }

    impl NamespaceGuard {
        pub fn new() -> Result<Self> {
            let mut original_ns = Vec::new();
            let ns_types = [
                ("user", "/proc/self/ns/user"),
                ("mnt", "/proc/self/ns/mnt"),
                ("pid", "/proc/self/ns/pid"),
                ("net", "/proc/self/ns/net"),
                ("uts", "/proc/self/ns/uts"),
                ("ipc", "/proc/self/ns/ipc"),
                ("cgroup", "/proc/self/ns/cgroup"),
            ];

            for (name, path) in ns_types {
                if let Ok(file) = fs::File::open(path) {
                    original_ns.push((name.to_string(), file));
                }
            }

            Ok(Self {
                original_ns,
                cleanup_mount: false,
            })
        }

        pub fn set_cleanup_mount(&mut self, cleanup: bool) {
            self.cleanup_mount = cleanup;
        }
    }

    impl Drop for NamespaceGuard {
        fn drop(&mut self) {
            // Restore original namespaces
            for (name, file) in &self.original_ns {
                let _ = nix::sched::setns(file, nix::sched::CloneFlags::empty());
            }

            // Cleanup mount namespace if requested
            if self.cleanup_mount {
                let _ = nix::mount::umount2("/tmp/sandbox", nix::mount::MntFlags::MNT_DETACH);
            }
        }
    }

    /// Create new namespaces and return guard for cleanup
    pub fn create_namespaces(config: &NamespaceConfig) -> Result<NamespaceGuard> {
        let mut flags = CloneFlags::empty();

        if config.enable_user {
            flags |= CloneFlags::CLONE_NEWUSER;
        }
        if config.enable_mount {
            flags |= CloneFlags::CLONE_NEWNS;
        }
        if config.enable_pid {
            flags |= CloneFlags::CLONE_NEWPID;
        }
        if config.enable_network {
            flags |= CloneFlags::CLONE_NEWNET;
        }
        if config.enable_uts {
            flags |= CloneFlags::CLONE_NEWUTS;
        }
        if config.enable_ipc {
            flags |= CloneFlags::CLONE_NEWIPC;
        }
        if config.enable_cgroup {
            flags |= CloneFlags::CLONE_NEWCGROUP;
        }

        // Fork to create new namespaces
        let child_fn = Box::new(|| {
            // This runs in the child process after clone
            0isize
        });

        let mut stack = vec![0u8; 1024 * 1024]; // 1MB stack
        let child_pid = unsafe {
            clone(
                child_fn,
                &mut stack[..],
                flags,
                None,
            )
        }.map_err(|e| LinuxSubstrateError::Namespace(e.to_string()))?;

        // Parent process - configure mappings
        if child_pid.as_raw() > 0 {
            // Write UID map
            if !config.uid_map.is_empty() {
                let map_content = config.uid_map.iter()
                    .map(|(inside, outside, count)| format!("{} {} {}", inside, outside, count))
                    .collect::<Vec<_>>()
                    .join("\n");
                fs::write(format!("/proc/{}/uid_map", child_pid), map_content)
                    .map_err(|e| LinuxSubstrateError::Io(e))?;
            }

            // Write GID map
            if !config.gid_map.is_empty() {
                let map_content = config.gid_map.iter()
                    .map(|(inside, outside, count)| format!("{} {} {}", inside, outside, count))
                    .collect::<Vec<_>>()
                    .join("\n");
                fs::write(format!("/proc/{}/gid_map", child_pid), map_content)
                    .map_err(|e| LinuxSubstrateError::Io(e))?;
            }

            // Deny setgroups
            fs::write(format!("/proc/{}/setgroups", child_pid), "deny")
                .map_err(|e| LinuxSubstrateError::Io(e))?;
        }

        Ok(NamespaceGuard::new()?)
    }

    /// Setup mount namespace with private tmpfs and bind mounts
    pub fn setup_mount_namespace(workspace_root: &Path, artifacts_dir: &Path) -> Result<()> {
        // Make mount namespace private
        mount(
            None::<&str>,
            "/",
            None::<&str>,
            MsFlags::MS_REC | MsFlags::MS_PRIVATE,
            None::<&str>,
        ).map_err(|e| LinuxSubstrateError::Namespace(e.to_string()))?;

        // Create private tmpfs for /tmp
        fs::create_dir_all("/tmp/sandbox").map_err(|e| LinuxSubstrateError::Io(e))?;
        mount(
            Some("tmpfs"),
            "/tmp/sandbox",
            Some("tmpfs"),
            MsFlags::MS_NOSUID | MsFlags::MS_NODEV | MsFlags::MS_NOEXEC,
            Some("size=64m,mode=0755"),
        ).map_err(|e| LinuxSubstrateError::Namespace(e.to_string()))?;

        // Bind mount source tree read-only at /work
        fs::create_dir_all("/work").map_err(|e| LinuxSubstrateError::Io(e))?;
        mount(
            Some(workspace_root.to_str().unwrap()),
            "/work",
            None::<&str>,
            MsFlags::MS_BIND | MsFlags::MS_REC | MsFlags::MS_RDONLY,
            None::<&str>,
        ).map_err(|e| LinuxSubstrateError::Namespace(e.to_string()))?;

        // Bind mount artifacts directory at /artifacts
        fs::create_dir_all("/artifacts").map_err(|e| LinuxSubstrateError::Io(e))?;
        mount(
            Some(artifacts_dir.to_str().unwrap()),
            "/artifacts",
            None::<&str>,
            MsFlags::MS_BIND,
            None::<&str>,
        ).map_err(|e| LinuxSubstrateError::Namespace(e.to_string()))?;

        // Create minimal /dev
        fs::create_dir_all("/dev").map_err(|e| LinuxSubstrateError::Io(e))?;
        for device in &["null", "zero", "urandom", "zero"] {
            let target = format!("/dev/{}", device);
            if !Path::new(&target).exists() {
                fs::File::create(&target).map_err(|e| LinuxSubstrateError::Io(e))?;
                mount(
                    Some(format!("/dev/{}", device).as_str()),
                    target.as_str(),
                    None::<&str>,
                    MsFlags::MS_BIND,
                    None::<&str>,
                ).map_err(|e| LinuxSubstrateError::Namespace(e.to_string()))?;
            }
        }

        Ok(())
    }

    /// Pivot root into new rootfs
    pub fn pivot_root(new_root: &Path) -> Result<()> {
        let new_root = CString::new(new_root.to_string_lossy().as_bytes()).unwrap();
        let put_old = CString::new("old").unwrap();

        // Change to new root
        std::os::unix::fs::chdir(&new_root).map_err(|e| LinuxSubstrateError::Io(e))?;

        // Pivot root
        nix::unistd::pivot_root(".", "old").map_err(|e| LinuxSubstrateError::Namespace(e.to_string()))?;

        // Unmount old root
        nix::mount::umount2("old", nix::mount::MntFlags::MNT_DETACH)
            .map_err(|e| LinuxSubstrateError::Namespace(e.to_string()))?;

        // Remove old directory
        fs::remove_dir("old").ok();

        Ok(())
    }

    /// Setup minimal /dev
    fn setup_dev() -> Result<()> {
        fs::create_dir_all("/dev").map_err(|e| LinuxSubstrateError::Io(e))?;
        
        let devices = ["null", "zero", "urandom", "full", "zero", "random"];
        for device in &devices {
            let target = format!("/dev/{}", device);
            if !Path::new(&target).exists() {
                fs::File::create(&target).map_err(|e| LinuxSubstrateError::Io(e))?;
                mount(
                    Some(format!("/dev/{}", device).as_str()),
                    target.as_str(),
                    None::<&str>,
                    MsFlags::MS_BIND,
                    None::<&str>,
                ).map_err(|e| LinuxSubstrateError::Namespace(e.to_string()))?;
            }
        }
        Ok(())
    }
}

/// Re-export the Linux namespace types and functions
#[cfg(target_os = "linux")]
pub use linux_namespace::*;

/// Stub implementations for non-Linux platforms
#[cfg(not(target_os = "linux"))]
mod stub_namespace {
    use crate::error::{LinuxSubstrateError, Result};
    use std::path::Path;

    #[derive(Debug, Clone, Default)]
    pub struct NamespaceConfig {
        pub enable_user: bool,
        pub enable_mount: bool,
        pub enable_pid: bool,
        pub enable_network: bool,
        pub enable_uts: bool,
        pub enable_ipc: bool,
        pub enable_cgroup: bool,
        pub uid_map: Vec<(u32, u32, u32)>,
        pub gid_map: Vec<(u32, u32, u32)>,
        pub mount_propagation: MountPropagation,
    }

    #[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
    pub enum MountPropagation {
        #[default]
        Private,
        Slave,
        Shared,
        Unchanged,
    }

    pub struct NamespaceGuard;

    impl NamespaceGuard {
        pub fn new() -> Result<Self> {
            Err(LinuxSubstrateError::Unavailable("Namespaces not supported on this platform".to_string()))
        }

        pub fn set_cleanup_mount(&mut self, _cleanup: bool) {}
    }

    pub fn create_namespaces(_config: &NamespaceConfig) -> Result<NamespaceGuard> {
        Err(LinuxSubstrateError::Unavailable("Namespaces not supported on this platform".to_string()))
    }

    pub fn setup_mount_namespace(_workspace_root: &Path, _artifacts_dir: &Path) -> Result<()> {
        Err(LinuxSubstrateError::Unavailable("Mount namespaces not supported on this platform".to_string()))
    }

    pub fn pivot_root(_new_root: &Path) -> Result<()> {
        Err(LinuxSubstrateError::Unavailable("Pivot root not supported on this platform".to_string()))
    }
}

/// Re-export the stub types for non-Linux platforms
#[cfg(not(target_os = "linux"))]
pub use stub_namespace::*;