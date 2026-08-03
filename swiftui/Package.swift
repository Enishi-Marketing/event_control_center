// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "EventControlCenter",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "EventControlCenter", targets: ["EventControlCenter"]),
    ],
    targets: [
        .executableTarget(name: "EventControlCenter")
    ]
)
