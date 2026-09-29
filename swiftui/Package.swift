// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "EventControlCenter",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "EventControlCenter", targets: ["EventControlCenter"]),
    ],
    dependencies: [
        .package(url: "https://github.com/sparkle-project/Sparkle", exact: "2.10.0"),
    ],
    targets: [
        .executableTarget(
            name: "EventControlCenter",
            dependencies: [.product(name: "Sparkle", package: "Sparkle")]
        )
    ]
)
