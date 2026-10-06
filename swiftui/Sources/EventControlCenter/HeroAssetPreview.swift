import AppKit
import ImageIO
import QuickLookThumbnailing
import SwiftUI
import UniformTypeIdentifiers

/// Keeps image decoding and Google Drive preview requests away from the UI actor.
private actor HeroPreviewStore {
    static let shared = HeroPreviewStore()

    private var images: [String: Data] = [:]
    private var pending: [String: Task<Data?, Never>] = [:]

    func image(for asset: HeroAsset, minimumSize: CGFloat, allowDriveFetch: Bool) async -> Data? {
        let localPaths = [asset.thumbnailPath, asset.exportPath, asset.needsEditPath]
            .compactMap { $0 }.filter { !$0.isEmpty }
        let drivePaths = [asset.webPath, asset.masterPath, asset.matchedLibraryPath, asset.sourcePath]
            .compactMap { $0 }.filter { !$0.isEmpty }
        let paths = allowDriveFetch ? localPaths + drivePaths : localPaths
        // Quick Look always requests a 400px image, so one result is suitable for
        // both the list thumbnail and the selected-photo preview.  Keeping this
        // key independent of view size makes those two views share an in-flight
        // request instead of loading the same Drive file twice.
        let key = asset.assetId + "|\(allowDriveFetch)|" + paths.joined(separator: "|")
        if let image = images[key] { return image }
        if let task = pending[key] { return await task.value }

        let task = Task.detached(priority: .utility) {
            await Self.load(paths: paths, minimumSize: minimumSize)
        }
        pending[key] = task
        let image = await task.value
        pending[key] = nil
        if let image { images[key] = image }
        return image
    }

    private nonisolated static func load(paths: [String], minimumSize: CGFloat) async -> Data? {
        for path in paths {
            if Task.isCancelled { return nil }
            if let image = await preview(at: URL(fileURLWithPath: path), minimumSize: minimumSize) {
                return image
            }
        }
        return nil
    }

    private nonisolated static func preview(at url: URL, minimumSize: CGFloat) async -> Data? {
        let request = QLThumbnailGenerator.Request(
            fileAt: url,
            size: CGSize(width: 400, height: 400),
            scale: 1,
            representationTypes: .thumbnail
        )
        let quickLookImage = try? await QLThumbnailGenerator.shared.generateBestRepresentation(for: request).nsImage
        if let quickLookImage,
           max(quickLookImage.size.width, quickLookImage.size.height) >= minimumSize {
            return quickLookImage.tiffRepresentation
        }

        // ImageIO downsamples while decoding, so large originals do not enter UI memory.
        let largerPreview = await Task.detached(priority: .utility) { () -> Data? in
            guard let source = CGImageSourceCreateWithURL(url as CFURL, [kCGImageSourceShouldCache: false] as CFDictionary),
                  let image = CGImageSourceCreateThumbnailAtIndex(source, 0, [
                    kCGImageSourceCreateThumbnailFromImageAlways: true,
                    kCGImageSourceCreateThumbnailWithTransform: true,
                    kCGImageSourceThumbnailMaxPixelSize: 400
                  ] as CFDictionary) else { return nil }
            let output = NSMutableData()
            guard let destination = CGImageDestinationCreateWithData(output, UTType.jpeg.identifier as CFString, 1, nil) else {
                return nil
            }
            CGImageDestinationAddImage(destination, image, nil)
            return CGImageDestinationFinalize(destination) ? output as Data : nil
        }.value
        return largerPreview ?? quickLookImage?.tiffRepresentation
    }
}

struct HeroAssetPreview: View {
    let asset: HeroAsset
    let size: CGFloat
    // The list warms previews from Drive automatically.  The preview store keeps
    // that work outside the UI actor and deduplicates it with the selected view.
    var allowDriveFetch = true

    @State private var image: NSImage?
    @State private var loading = true
    @State private var retry = 0
    @State private var requestedDrivePreview = false

    private var canFetchFromDrive: Bool { allowDriveFetch || requestedDrivePreview }

    var body: some View {
        Group {
            if let image {
                Image(nsImage: image)
                    .resizable()
                    .aspectRatio(contentMode: size > 100 ? .fit : .fill)
                    .frame(width: size, height: size)
                    .clipped()
            } else if loading {
                ProgressView().frame(width: size, height: size)
            } else {
                Button {
                    requestedDrivePreview = true
                    retry += 1
                } label: {
                    VStack(spacing: 4) {
                        Image(systemName: "arrow.clockwise")
                        if size > 100 { Text("Load preview").font(.caption) }
                    }
                    .frame(width: size, height: size)
                }
                .buttonStyle(.plain)
                .help("Retry loading this preview from Google Drive")
            }
        }
        .background(.black.opacity(0.06), in: RoundedRectangle(cornerRadius: 6))
        .clipShape(RoundedRectangle(cornerRadius: 6))
        .task(id: "\(asset.assetId)|\(asset.thumbnailPath ?? "")|\(asset.exportPath ?? "")|\(canFetchFromDrive)|\(retry)") {
            loading = true
            image = await HeroPreviewStore.shared.image(
                for: asset, minimumSize: size, allowDriveFetch: canFetchFromDrive
            ).flatMap(NSImage.init(data:))
            loading = false
        }
    }
}
