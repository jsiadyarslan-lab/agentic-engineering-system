use crate::error::{MacOSSubstrateError, Result};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};

/// XPC connection for inter-process communication on macOS
pub struct XPCConnection {
    service_name: String,
    listener: Option<*mut std::ffi::c_void>, // xpc_connection_t
    connected: bool,
    message_handlers: Arc<Mutex<HashMap<String, Box<dyn Fn(&[u8]) -> Vec<u8> + Send + Sync>>>>,
}

impl XPCConnection {
    /// Create a new XPC connection to a service
    pub fn new(service_name: &str) -> Result<Self> {
        Ok(Self {
            service_name: service_name.to_string(),
            listener: None,
            connected: false,
            message_handlers: Arc::new(Mutex::new(HashMap::new())),
        })
    }

    /// Connect to the XPC service
    pub fn connect(&mut self) -> Result<()> {
        // In a real implementation, this would use xpc_connection_create_mach_service
        // For now, we'll just mark as connected
        self.connected = true;
        Ok(())
    }

    /// Disconnect from the XPC service
    pub fn disconnect(&mut self) -> Result<()> {
        self.connected = false;
        Ok(())
    }

    /// Send a message and wait for a reply
    pub fn send_message(&self, message: &[u8]) -> Result<Vec<u8>> {
        if !self.connected {
            return Err(MacOSSubstrateError::XPCConnection("Not connected".to_string()));
        }

        // In a real implementation, this would use xpc_connection_send_message_with_reply_sync
        // For now, return a dummy response
        Ok(vec![])
    }

    /// Send a message without waiting for a reply
    pub fn send_message_async(&self, message: &[u8]) -> Result<()> {
        if !self.connected {
            return Err(MacOSSubstrateError::XPCConnection("Not connected".to_string()));
        }

        // In a real implementation, this would use xpc_connection_send_message
        Ok(())
    }

    /// Register a message handler
    pub fn register_handler<F>(&mut self, message_type: &str, handler: F) -> Result<()>
    where
        F: Fn(&[u8]) -> Vec<u8> + Send + Sync + 'static,
    {
        let mut handlers = self.message_handlers.lock().unwrap();
        handlers.insert(message_type.to_string(), Box::new(handler));
        Ok(())
    }

    /// Check if connected
    pub fn is_connected(&self) -> bool {
        self.connected
    }

    /// Get the service name
    pub fn service_name(&self) -> &str {
        &self.service_name
    }
}

/// XPC listener for incoming connections
pub struct XPCListener {
    service_name: String,
    listener: Option<*mut std::ffi::c_void>, // xpc_connection_t
    handler: Arc<Mutex<dyn Fn(&[u8]) -> Vec<u8> + Send + Sync>>,
    running: bool,
}

impl XPCListener {
    /// Create a new XPC listener for a service
    pub fn new(service_name: &str, handler: impl Fn(&[u8]) -> Vec<u8> + Send + Sync + 'static) -> Result<Self> {
        Ok(Self {
            service_name: service_name.to_string(),
            listener: None,
            handler: Arc::new(Mutex::new(handler)),
            running: false,
        })
    }

    /// Start listening for connections
    pub fn start(&mut self) -> Result<()> {
        if self.running {
            return Ok(());
        }

        // In a real implementation, this would use xpc_connection_create_mach_service
        // and xpc_connection_set_event_handler
        self.running = true;
        Ok(())
    }

    /// Stop listening for connections
    pub fn stop(&mut self) -> Result<()> {
        self.running = false;
        Ok(())
    }

    /// Check if running
    pub fn is_running(&self) -> bool {
        self.running
    }
}

/// XPC message types
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum XPCMessage {
    Request { id: u64, method: String, params: serde_json::Value },
    Response { id: u64, result: serde_json::Value },
    Error { id: u64, code: i32, message: String },
    Notification { event: String, data: serde_json::Value },
}

impl XPCMessage {
    pub fn request(id: u64, method: &str, params: serde_json::Value) -> Self {
        Self::Request { id, method: method.to_string(), params }
    }

    pub fn response(id: u64, result: serde_json::Value) -> Self {
        Self::Response { id, result }
    }

    pub fn error(id: u64, code: i32, message: String) -> Self {
        Self::Error { id, code, message }
    }

    pub fn notification(event: &str, data: serde_json::Value) -> Self {
        Self::Notification { event: event.to_string(), data }
    }

    pub fn serialize(&self) -> Result<Vec<u8>, serde_json::Error> {
        serde_json::to_vec(self)
    }

    pub fn deserialize(data: &[u8]) -> Result<Self, serde_json::Error> {
        serde_json::from_slice(data)
    }
}

/// XPC message builder
pub struct XPCMessageBuilder {
    message: XPCMessage,
}

impl XPCMessageBuilder {
    pub fn request(id: u64, method: &str) -> Self {
        Self {
            message: XPCMessage::request(id, method, serde_json::Value::Null),
        }
    }

    pub fn response(id: u64) -> Self {
        Self {
            message: XPCMessage::response(id, serde_json::Value::Null),
        }
    }

    pub fn with_params(mut self, params: serde_json::Value) -> Self {
        if let XPCMessage::Request { ref mut params, .. } = self.message {
            *params = params;
        }
        self
    }

    pub fn with_result(mut self, result: serde_json::Value) -> Self {
        if let XPCMessage::Response { ref mut result: ref_mut_result, .. } = self.message {
            *ref_mut_result = result;
        }
        self
    }

    pub fn with_error(mut self, code: i32, message: String) -> Self {
        self.message = XPCMessage::error(0, code, message);
        self
    }

    pub fn build(self) -> XPCMessage {
        self.message
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_xpc_message_serialization() {
        let msg = XPCMessage::request(1, "test_method", serde_json::json!({"key": "value"}));
        let serialized = msg.serialize().unwrap();
        let deserialized = XPCMessage::deserialize(&serialized).unwrap();
        
        match deserialized {
            XPCMessage::Request { id, method, params } => {
                assert_eq!(id, 1);
                assert_eq!(method, "test_method");
                assert_eq!(params, serde_json::json!({"key": "value"}));
            }
            _ => panic!("Wrong message type"),
        }
    }

    #[test]
    fn test_xpc_connection_creation() {
        let conn = XPCConnection::new("test_service");
        assert!(conn.is_ok());
    }
}