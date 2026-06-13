pub struct CameraStream;

pub fn open(_label: &str) -> Result<CameraStream, String> {
    Err("native macOS camera capture is not implemented yet".into())
}

pub fn open_with_retry(label: &str, attempts: u32, delay_ms: u64) -> Result<CameraStream, String> {
    let mut last = String::new();
    for i in 0..attempts {
        match open(label) {
            Ok(stream) => return Ok(stream),
            Err(e) => {
                last = e;
                if i + 1 < attempts {
                    std::thread::sleep(std::time::Duration::from_millis(delay_ms));
                }
            }
        }
    }
    Err(last)
}

impl CameraStream {
    pub fn next_jpeg(&self) -> Option<Vec<u8>> {
        None
    }

    pub fn next_jpeg_timeout(&self, _timeout_ms: u64) -> Option<Vec<u8>> {
        None
    }
}
