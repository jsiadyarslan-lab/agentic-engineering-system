use crate::error::{WindowsSubstrateError, Result};
use crate::types::JobObjectLimits;
use std::os::windows::io::AsRawHandle;
use std::ptr;
use std::mem;
use windows::Win32::Foundation::*;
use windows::Win32::System::JobObjects::*;
use windows::Win32::System::Threading::*;
use windows::Win32::System::Memory::*;
use windows::Win32::System::Diagnostics::Debug::*;
use windows::Win32::Security::*;
use windows::core::*;

/// Job Object wrapper for Windows process isolation and resource limits
pub struct JobObject {
    handle: HANDLE,
    limits_applied: bool,
}

impl JobObject {
    /// Create a new Job Object
    pub fn new() -> Result<Self> {
        unsafe {
            let handle = CreateJobObjectW(None, PCWSTR(ptr::null()));
            if handle.is_invalid() {
                return Err(WindowsSubstrateError::JobObjectApi(
                    format!("Failed to create Job Object: {}", std::io::Error::last_os_error())
                ));
            }
            Ok(Self {
                handle,
                limits_applied: false,
            })
        }
    }

    /// Create a Job Object with a name
    pub fn new_named(name: &str) -> Result<Self> {
        let name_wide: Vec<u16> = name.encode_utf16().chain(Some(0)).collect();
        unsafe {
            let handle = CreateJobObjectW(None, PCWSTR(name_wide.as_ptr()));
            if handle.is_invalid() {
                return Err(WindowsSubstrateError::JobObjectApi(
                    format!("Failed to create named Job Object: {}", std::io::Error::last_os_error())
                ));
            }
            Ok(Self {
                handle,
                limits_applied: false,
            })
        }
    }

    /// Apply resource limits to the Job Object
    pub fn set_limits(&mut self, limits: &crate::types::JobObjectLimits) -> Result<()> {
        if self.limits_applied {
            return Err(WindowsSubstrateError::JobObject("Limits already applied".to_string()));
        }

        unsafe {
            // Set basic limit information
            let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();

            // Basic limits
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_ACTIVE_PROCESS
                | JOB_OBJECT_LIMIT_JOB_MEMORY
                | JOB_OBJECT_LIMIT_PROCESS_MEMORY
                | JOB_OBJECT_LIMIT_JOB_TIME
                | JOB_OBJECT_LIMIT_PROCESS_TIME
                | JOB_OBJECT_LIMIT_AFFINITY
                | JOB_OBJECT_LIMIT_PRIORITY_CLASS
                | JOB_OBJECT_LIMIT_SCHEDULING_CLASS
                | JOB_OBJECT_LIMIT_ACTIVE_PROCESS; // Use ACTIVE_PROCESS instead of PROCESS_COUNT

            // Process memory limit
            if let Some(limit) = limits.process_memory_limit {
                info.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_PROCESS_MEMORY;
                info.ProcessMemoryLimit = limit as usize;
            }

            // Job memory limit
            if let Some(limit) = limits.job_memory_limit {
                info.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_JOB_MEMORY;
                info.JobMemoryLimit = limit as usize;
            }

            // Process time limit
            if let Some(limit) = limits.process_time_limit {
                info.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_PROCESS_TIME;
                info.PerProcessUserTimeLimit = (limit * 10000000) as i64; // Convert to 100ns units
            }

            // Job time limit
            if let Some(limit) = limits.job_time_limit {
                info.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_JOB_TIME;
                info.PerJobUserTimeLimit = (limit * 10000000) as i64;
            }

            // CPU rate control - use available constants
            if let Some(rate) = limits.cpu_rate {
                info.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_RATE_CONTROL;
                // Use available CPU rate control constants
            }

            // Max processes
            if let Some(max) = limits.max_processes {
                info.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_ACTIVE_PROCESS;
                info.BasicLimitInformation.ActiveProcessLimit = max;
            }

            // CPU affinity
            if let Some(ref affinity) = limits.cpu_affinity {
                let mut mask: usize = 0;
                for &cpu in affinity {
                    if cpu < 64 {
                        mask |= 1 << cpu;
                    }
                }
                info.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_AFFINITY;
                info.BasicLimitInformation.Affinity = mask;
            }

            // Apply the limits
            let result = SetInformationJobObject(
                self.handle,
                JobObjectExtendedLimitInformation,
                &info as *const _ as *const _,
                std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            );

            if result.is_err() {
                return Err(WindowsSubstrateError::JobObjectApi(
                    format!("Failed to set Job Object limits: {}", std::io::Error::last_os_error())
                ));
            }

            // Set IO rate control if specified - use available API
            if let Some(io_rate) = limits.io_rate {
                let io_info = JOBOBJECT_IO_RATE_CONTROL_INFORMATION {
                    MaxIops: io_rate,
                    ..Default::default()
                };
                let result = SetInformationJobObject(
                    self.handle,
                    JobObjectCpuRateControlInformation,
                    &io_info as *const _ as *const _,
                    std::mem::size_of::<JOBOBJECT_IO_RATE_CONTROL_INFORMATION>() as u32,
                );
                if result.is_err() {
                    return Err(WindowsSubstrateError::JobObjectApi(
                        format!("Failed to set IO rate control: {}", std::io::Error::last_os_error())
                    ));
                }
            }

            // Set process memory limit if specified
            if let Some(limit) = limits.process_memory_limit {
                let info = JOBOBJECT_BASIC_LIMIT_INFORMATION {
                    LimitFlags: JOB_OBJECT_LIMIT_PROCESS_MEMORY,
                    ProcessMemoryLimit: limit as usize,
                    ..Default::default()
                };
                let result = SetInformationJobObject(
                    self.handle,
                    JobObjectBasicLimitInformation,
                    &info as *const _ as *const _,
                    std::mem::size_of::<JOBOBJECT_BASIC_LIMIT_INFORMATION>() as u32,
                );
                if result.is_err() {
                    return Err(WindowsSubstrateError::JobObjectApi(
                        format!("Failed to set process memory limit: {}", std::io::Error::last_os_error())
                    ));
                }
            }

            // Set job memory limit
            if let Some(limit) = limits.job_memory_limit {
                let info = JOBOBJECT_BASIC_LIMIT_INFORMATION {
                    LimitFlags: JOB_OBJECT_LIMIT_JOB_MEMORY,
                    JobMemoryLimit: limit as usize,
                    ..Default::default()
                };
                let result = SetInformationJobObject(
                    self.handle,
                    JobObjectBasicLimitInformation,
                    &info as *const _ as *const _,
                    std::mem::size_of::<JOBOBJECT_BASIC_LIMIT_INFORMATION>() as u32,
                );
                if result.is_err() {
                    return Err(WindowsSubstrateError::JobObjectApi(
                        format!("Failed to set job memory limit: {}", std::io::Error::last_os_error())
                    ));
                }
            }

            self.limits_applied = true;
        }

        Ok(())
    }

    /// Assign a process to the Job Object
    pub fn assign_process(&self, process_handle: HANDLE) -> Result<()> {
        unsafe {
            let result = AssignProcessToJobObject(self.handle, process_handle);
            if result.is_err() {
                return Err(WindowsSubstrateError::JobObjectApi(
                    format!("Failed to assign process to Job Object: {}", std::io::Error::last_os_error())
                ));
            }
        }
        Ok(())
    }

    /// Assign current process to the Job Object
    pub fn assign_current_process(&self) -> Result<()> {
        unsafe {
            let current_process = GetCurrentProcess();
            let result = AssignProcessToJobObject(self.handle, current_process);
            if result.is_err() {
                return Err(WindowsSubstrateError::JobObjectApi(
                    format!("Failed to assign current process to Job Object: {}", std::io::Error::last_os_error())
                ));
            }
        }
        Ok(())
    }

    /// Query Job Object basic accounting information
    pub fn query_basic_accounting(&self) -> Result<JOBOBJECT_BASIC_ACCOUNTING_INFORMATION> {
        unsafe {
            let mut info: JOBOBJECT_BASIC_ACCOUNTING_INFORMATION = std::mem::zeroed();
            let result = QueryInformationJobObject(
                self.handle,
                JobObjectBasicAccountingInformation,
                &mut info as *mut _ as *mut _,
                std::mem::size_of::<JOBOBJECT_BASIC_ACCOUNTING_INFORMATION>() as u32,
                None,
            );
            if result.is_err() {
                return Err(WindowsSubstrateError::JobObjectApi(
                    format!("Failed to query Job Object accounting: {}", std::io::Error::last_os_error())
                ));
            }
            Ok(info)
        }
    }

    /// Query Job Object basic limit information
    pub fn query_basic_limits(&self) -> Result<JOBOBJECT_BASIC_LIMIT_INFORMATION> {
        unsafe {
            let mut info: JOBOBJECT_BASIC_LIMIT_INFORMATION = std::mem::zeroed();
            let result = QueryInformationJobObject(
                self.handle,
                JobObjectBasicLimitInformation,
                &mut info as *mut _ as *mut _,
                std::mem::size_of::<JOBOBJECT_BASIC_LIMIT_INFORMATION>() as u32,
                None,
            );
            if result.is_err() {
                return Err(WindowsSubstrateError::JobObjectApi(
                    format!("Failed to query Job Object limits: {}", std::io::Error::last_os_error())
                ));
            }
            Ok(info)
        }
    }

    /// Query Job Object extended limit information
    pub fn query_extended_limits(&self) -> Result<JOBOBJECT_EXTENDED_LIMIT_INFORMATION> {
        unsafe {
            let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            let result = QueryInformationJobObject(
                self.handle,
                JobObjectExtendedLimitInformation,
                &mut info as *mut _ as *mut _,
                std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                None,
            );
            if result.is_err() {
                return Err(WindowsSubstrateError::JobObjectApi(
                    format!("Failed to query Job Object extended limits: {}", std::io::Error::last_os_error())
                ));
            }
            Ok(info)
        }
    }

    /// Get the Job Object handle
    pub fn handle(&self) -> HANDLE {
        self.handle
    }

    /// Check if limits have been applied
    pub fn limits_applied(&self) -> bool {
        self.limits_applied
    }
}

impl Drop for JobObject {
    fn drop(&mut self) {
        if !self.handle.is_invalid() {
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
            limits_applied: false,
        })
    }
}