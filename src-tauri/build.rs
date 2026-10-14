fn main() {
    // Dependency linker arguments do not propagate to the final executable.
    // ScreenCaptureKit's Swift bridge needs the system Swift runtime here too.
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("macos") {
        println!("cargo:rustc-link-arg=-Wl,-rpath,/usr/lib/swift");
    }
    tauri_build::build();
}
