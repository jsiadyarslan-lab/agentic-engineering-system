//! Windows Job Object wrappers for resource limits and process isolation

use windows::Win32::Foundation::*;
use windows::Win32::System::JobObjects::*;
use windows::Win32::System::Threading::*;
use windows::core::*;
use std::ptr;

type WinResult<T> = windows::core::Result<T>;

/// Job Object handle wrapper
pub struct JobObject {
    handle: HANDLE,
}

impl JobObject {
    /// Create a new Job Object
    pub fn new() -> WinResult<Self> {
        unsafe {
            let handle = CreateJobObjectW(None, PCWSTR(ptr::null()));
            handle.map(|h| Self { handle: h })
        }
    }

    /// Create a Job Object with a name
    pub fn new_named(name: &str) -> WinResult<Self> {
        let name_wide: Vec<u16> = name.encode_utf16().chain(Some(0)).collect();
        unsafe {
            let handle = CreateJobObjectW(None, PCWSTR(name_wide.as_ptr()));
            handle.map(|h| Self { handle: h })
        }
    }

    /// Get the Job Object handle
    pub fn handle(&self) -> HANDLE {
        self.handle
    }

    /// Assign a process to the Job Object
    pub fn assign_process(&self, process_handle: HANDLE) -> WinResult<()> {
        unsafe {
            let result = AssignProcessToJobObject(self.handle, process_handle);
            if result.is_err() {
                return Err(Error::from_win32());
            }
            Ok(())
        }
    }

    /// Assign current process to the Job Object
    pub fn assign_current_process(&self) -> WinResult<()> {
        unsafe {
            let current_process = GetCurrentProcess();
            let result = AssignProcessToJobObject(self.handle, current_process);
            if result.is_err() {
                return Err(Error::from_win32());
            }
            Ok(())
        }
    }

    /// Set basic limit information
    pub fn set_basic_limits(&self, limits: &JobObjectLimits) -> WinResult<()> {
        unsafe {
            let mut info: JOBOBJECT_BASIC_LIMIT_INFORMATION = std::mem::zeroed();
            
            info.LimitFlags = JOB_OBJECT_LIMIT_ACTIVE_PROCESS
                | JOB_OBJECT_LIMIT_JOB_MEMORY
                | JOB_OBJECT_LIMIT_PROCESS_MEMORY
                | JOB_OBJECT_LIMIT_JOB_TIME
                | JOB_OBJECT_LIMIT_PROCESS_TIME
                | JOB_OBJECT_LIMIT_AFFINITY
                | JOB_OBJECT_LIMIT_PRIORITY_CLASS
                | JOB_OBJECT_LIMIT_SCHEDULING_CLASS
                | JOB_OBJECT_LIMIT_PROCESS_TIME
                | JOB_OBJECT_LIMIT_JOB_READ_BYTES
                | JOB_OBJECT_LIMIT_JOB_WRITE_BYTES
                | JOB_OBJECT_LIMIT_RATE_CONTROL
                | JOB_OBJECT_LIMIT_IO_RATE_CONTROL;

            // Apply limits from the struct
            if let Some(mem_limit) = limits.memory_limit {
                info.LimitFlags |= JOB_OBJECT_LIMIT_JOB_MEMORY;
                info.MaximumWorkingSetSize = mem_limit as usize;
            }
            if let Some(proc_mem_limit) = limits.process_memory_limit {
                info.LimitFlags |= JOB_OBJECT_LIMIT_PROCESS_MEMORY;
                info.MinimumWorkingSetSize = proc_mem_limit as usize;
            }
            if let Some(max_procs) = limits.max_processes {
                info.LimitFlags |= JOB_OBJECT_LIMIT_ACTIVE_PROCESS;
                info.ActiveProcessLimit = max_procs;
            }
            if let Some(job_time) = limits.job_time_limit {
                info.LimitFlags |= JOB_OBJECT_LIMIT_JOB_TIME;
                info.PerJobUserTimeLimit = job_time as i64;
            }
            if let Some(proc_time) = limits.process_time_limit {
                info.LimitFlags |= JOB_OBJECT_LIMIT_PROCESS_TIME;
                info.PerProcessUserTimeLimit = proc_time as i64;
            }

            let result = SetInformationJobObject(
                self.handle,
                JobObjectBasicLimitInformation,
                &info as *const _ as *const _,
                std::mem::size_of::<JOBOBJECT_BASIC_LIMIT_INFORMATION>() as u32,
            );

            if result.is_err() {
                return Err(Error::from_win32());
            }

            Ok(())
        }
    }
}

impl Drop for JobObject {
    fn drop(&mut self) {
        if self.handle.0 != ptr::null_mut() {
            unsafe {
                let _ = CloseHandle(self.handle);
            }
        }
    }
}

impl Default for JobObject {
    fn default() -> Self {
        Self::new().unwrap_or_else(|_| Self {
            handle: HANDLE(ptr::null_mut()),
        })
    }
}

/// Job Object limits configuration
#[derive(Debug, Clone, Default)]
pub struct JobObjectLimits {
    pub memory_limit: Option<u64>,
    pub job_memory_limit: Option<u64>,
    pub process_memory_limit: Option<u64>,
    pub cpu_affinity: Option<Vec<usize>>,
    pub cpu_rate: Option<u32>,
    pub max_processes: Option<u32>,
    pub io_rate: Option<u64>,
    pub process_time_limit: Option<u64>,
    pub job_time_limit: Option<u64>,
}

/// Limit flags for Job Objects (re-export from windows crate with simpler names)
pub mod limits {
    pub const JOB_OBJECT_LIMIT_ACTIVE_PROCESS: u32 = windows::Win32::System::JobObjects::JOB_OBJECT_LIMIT_ACTIVE_PROCESS.0;
    pub const JOB_OBJECT_LIMIT_JOB_MEMORY: u32 = windows::Win32::System::JobObjects::JOB_OBJECT_LIMIT_JOB_MEMORY.0;
    pub const JOB_OBJECT_LIMIT_PROCESS_MEMORY: u32 = windows::Win32::System::JobObjects::JOB_OBJECT_LIMIT_PROCESS_MEMORY.0;
    pub const JOB_OBJECT_LIMIT_JOB_TIME: u32 = windows::Win32::System::JobObjects::JOB_OBJECT_LIMIT_JOB_TIME.0;
    pub const JOB_OBJECT_LIMIT_PROCESS_TIME: u32 = windows::Win32::System::JobObjects::JOB_OBJECT_LIMIT_PROCESS_TIME.0;
    pub const JOB_OBJECT_LIMIT_AFFINITY: u32 = windows::Win32::System::JobObjects::JOB_OBJECT_LIMIT_AFFINITY.0;
    pub const JOB_OBJECT_LIMIT_PRIORITY_CLASS: u32 = windows::Win32::System::JobObjects::JOB_OBJECT_LIMIT_PRIORITY_CLASS.0;
    pub const JOB_OBJECT_LIMIT_SCHEDULING_CLASS: u32 = windows::Win32::System::JobObjects::JOB_OBJECT_LIMIT_SCHEDULING_CLASS.0;
    pub const JOB_OBJECT_LIMIT_PROCESS_COUNT: u32 = windows::Win32::System::JobObjects::JOB_OBJECT_LIMIT_ACTIVE_PROCESS.0;
    pub const JOB_OBJECT_LIMIT_JOB_READ_BYTES: u32 = windows::Win32::System::JobObjects::JOB_OBJECT_LIMIT_JOB_READ_BYTES.0;
    pub const JOB_OBJECT_LIMIT_JOB_WRITE_BYTES: u32 = windows::Win32::System::JobObjects::JOB_OBJECT_LIMIT_JOB_WRITE_BYTES.0;
    pub const JOB_OBJECT_LIMIT_RATE_CONTROL: u32 = windows::Win32::System::JobObjects::JOB_OBJECT_LIMIT_RATE_CONTROL.0;
    pub const JOB_OBJECT_LIMIT_IO_RATE_CONTROL: u32 = windows::Win32::System::JobObjects::JOB_OBJECT_LIMIT_IO_RATE_CONTROL.0;
}

/// Process management utilities
pub mod process {
    use super::*;
    use std::ptr;

    /// Get current process handle
    pub fn current_process() -> HANDLE {
        unsafe { GetCurrentProcess() }
    }

    /// Get current process ID
    pub fn current_process_id() -> u32 {
        unsafe { GetCurrentProcessId() }
    }

    /// Get current thread ID
    pub fn current_thread_id() -> u32 {
        unsafe { GetCurrentThreadId() }
    }

    /// Open a process by ID
    pub fn open_process(pid: u32, desired_access: u32, inherit_handle: bool) -> WinResult<HANDLE> {
        unsafe {
            let handle = OpenProcess(PROCESS_ACCESS_RIGHTS(desired_access), inherit_handle, pid)?;
            if handle.0 == ptr::null_mut() {
                return Err(Error::from_win32());
            }
            Ok(handle)
        }
    }

    /// Terminate a process
    pub fn terminate_process(handle: HANDLE, exit_code: u32) -> WinResult<()> {
        unsafe {
            let result = TerminateProcess(handle, exit_code);
            if result.is_err() {
                return Err(Error::from_win32());
            }
            Ok(())
        }
    }

    /// Wait for process to exit
    pub fn wait_for_process(handle: HANDLE, timeout: u32) -> WinResult<u32> {
        unsafe {
            let result = WaitForSingleObject(handle, timeout);
            match result {
                WAIT_OBJECT_0 => {
                    let mut exit_code: u32 = 0;
                    unsafe {
                        let _ = GetExitCodeProcess(handle, &mut exit_code);
                    }
                    Ok(exit_code)
                }
                WAIT_TIMEOUT => Err(Error::new(E_ABORT, "Timeout")),
                _ => Err(Error::from_win32()),
            }
        }
    }
}

/// Query utilities for Job Objects
pub mod query {
    use super::*;

    /// Query basic accounting information
    pub fn query_basic_accounting(handle: HANDLE) -> WinResult<JOBOBJECT_BASIC_ACCOUNTING_INFORMATION> {
        unsafe {
            let mut info: JOBOBJECT_BASIC_ACCOUNTING_INFORMATION = std::mem::zeroed();
            let result = QueryInformationJobObject(
                handle,
                JobObjectBasicAccountingInformation,
                &mut info as *mut _ as *mut _,
                std::mem::size_of::<JOBOBJECT_BASIC_ACCOUNTING_INFORMATION>() as u32,
                None,
            );
            if result.is_err() {
                return Err(Error::from_win32());
            }
            Ok(info)
        }
    }

    /// Query basic limit information
    pub fn query_basic_limits(handle: HANDLE) -> WinResult<JOBOBJECT_BASIC_LIMIT_INFORMATION> {
        unsafe {
            let mut info: JOBOBJECT_BASIC_LIMIT_INFORMATION = std::mem::zeroed();
            let result = QueryInformationJobObject(
                handle,
                JobObjectBasicLimitInformation,
                &mut info as *mut _ as *mut _,
                std::mem::size_of::<JOBOBJECT_BASIC_LIMIT_INFORMATION>() as u32,
                None,
            );
            if result.is_err() {
                return Err(Error::from_win32());
            }
            Ok(info)
        }
    }

    /// Query extended limit information
    pub fn query_extended_limits(handle: HANDLE) -> WinResult<JOBOBJECT_EXTENDED_LIMIT_INFORMATION> {
        unsafe {
            let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            let result = QueryInformationJobObject(
                handle,
                JobObjectExtendedLimitInformation,
                &mut info as *mut _ as *mut _,
                std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                None,
            );
            if result.is_err() {
                return Err(Error::from_win32());
            }
            Ok(info)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_job_object_creation() {
        let job = JobObject::new();
        assert!(job.is_ok());
    }

    #[test]
    fn test_named_job_object() {
        let job = JobObject::new_named("test-job");
        assert!(job.is_ok());
    }
}