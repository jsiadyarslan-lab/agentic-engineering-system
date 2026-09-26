fn main() -> Result<(), Box<dyn std::error::Error>> {
    tonic_build::configure()
        .build_server(true)
        .build_client(true)
        .compile_protos(
            &["src/substrate/proto/substrate.proto"],
            &["src/substrate/proto"],
        )?;
    Ok(())
}