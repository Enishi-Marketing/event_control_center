import AppKit
import SwiftUI

@main
struct EventControlCenterApp: App {
    @StateObject private var appState = AppState()
    @NSApplicationDelegateAdaptor(EventControlCenterDelegate.self) private var appDelegate

    var body: some Scene {
        WindowGroup("Event Control Center") {
            ContentView()
                .environmentObject(appState)
                .preferredColorScheme(.dark)
                .tint(.cyan)
                .task { await appState.loadConfiguration() }
        }
        .defaultSize(width: 1280, height: 820)
        .windowResizability(.contentMinSize)
    }
}

final class EventControlCenterDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        DispatchQueue.main.async {
            NSApp.activate(ignoringOtherApps: true)
        }
    }

    func applicationShouldHandleReopen(
        _ sender: NSApplication,
        hasVisibleWindows flag: Bool
    ) -> Bool {
        NSApp.activate(ignoringOtherApps: true)
        return true
    }
}

@MainActor
final class AppState: ObservableObject {
    @Published var configuration: ConfigSnapshot?
    @Published var isWorking = false
    @Published var errorMessage: String?
    @Published var notice: String?

    private let client: BackendClient?

    init() {
        do {
            client = try BackendClient()
        } catch {
            client = nil
            errorMessage = error.localizedDescription
        }
    }

    func loadConfiguration() async {
        await perform(showSuccess: false) {
            let config: ConfigSnapshot = try await self.request("config", payload: EmptyPayload())
            self.configuration = config
        }
    }

    func createEvent(_ payload: CreateEventPayload) async -> CreatedEvent? {
        var result: CreatedEvent?
        await perform(showSuccess: false) {
            result = try await self.request("create_event", payload: payload)
        }
        return result
    }

    func scan(source: String, gap: Int) async -> MediaScan? {
        struct Payload: Codable { let source: String; let sessionGapMinutes: Int }
        var result: MediaScan?
        await perform(showSuccess: false) {
            result = try await self.request("scan_media", payload: Payload(source: source, sessionGapMinutes: gap))
        }
        return result
    }

    func availableSources() async -> [ImportSourceInfo] {
        guard let client else { return [] }
        do {
            let result: ImportSourcesResponse = try await client.request(
                "available_sources",
                payload: EmptyPayload()
            )
            return result.sources
        } catch {
            return []
        }
    }

    func importMedia(
        _ payload: ImportMediaPayload,
        onProgress: @escaping (ImportStreamEvent) -> Void
    ) async -> ImportOutcome? {
        guard let client else {
            errorMessage = "The Python backend is unavailable. Set ECC_BACKEND_ROOT and ECC_PYTHON, then restart the app."
            return nil
        }

        isWorking = true
        defer { isWorking = false }
        do {
            let events = try client.importEvents(payload: payload)
            var outcome: ImportOutcome?
            for try await event in events {
                onProgress(event)
                if event.type == "error" {
                    throw BackendError.failed(event.error ?? "The import could not be completed.")
                }
                if event.type == "completed" {
                    outcome = event.outcome
                }
            }
            guard let outcome else {
                throw BackendError.failed("The import stopped before returning a summary.")
            }
            return outcome
        } catch {
            errorMessage = error.localizedDescription
            return nil
        }
    }

    func cleanupImportedMedia(_ payload: SourceCleanupPayload) async -> SourceCleanupResult? {
        var result: SourceCleanupResult?
        await perform(showSuccess: false) {
            result = try await self.request("cleanup_imported_media", payload: payload)
        }
        return result
    }

    func search(source: String) async -> SearchIndex? {
        struct Payload: Codable { let source: String }
        var result: SearchIndex?
        await perform(showSuccess: false) {
            result = try await self.request("search_events", payload: Payload(source: source))
        }
        return result
    }

    func saveSettings(_ payload: SettingsPayload) async {
        await perform(showSuccess: false) {
            let config: ConfigSnapshot = try await self.request("save_settings", payload: payload)
            self.configuration = config
            self.notice = "Settings saved. New events will use the updated locations."
        }
    }

    func generateJPGs(folder: String, regenerateAll: Bool) async -> JPGResult? {
        struct Payload: Codable { let eventFolder: String; let regenerateAll: Bool }
        var result: JPGResult?
        await perform(showSuccess: false) {
            result = try await self.request("generate_jpgs", payload: Payload(eventFolder: folder, regenerateAll: regenerateAll))
        }
        return result
    }

    func updateMediaCounts(root: String) async -> CountResult? {
        struct Payload: Codable { let eventRoot: String }
        var result: CountResult?
        await perform(showSuccess: false) {
            result = try await self.request("update_media_counts", payload: Payload(eventRoot: root))
        }
        return result
    }

    func syncGoogleSheets(root: String) async -> GoogleSheetsSyncResult? {
        struct Payload: Codable { let eventRoot: String }
        var result: GoogleSheetsSyncResult?
        await perform(showSuccess: false) {
            result = try await self.request("sync_google_sheets", payload: Payload(eventRoot: root))
        }
        return result
    }

    func archiveCandidates(sourceRoot: String, archiveRoot: String) async -> [ArchiveCandidate]? {
        struct Payload: Codable { let sourceRoot: String; let archiveRoot: String }
        var result: ArchiveCandidatesResponse?
        await perform(showSuccess: false) {
            result = try await self.request(
                "archive_candidates",
                payload: Payload(sourceRoot: sourceRoot, archiveRoot: archiveRoot)
            )
        }
        return result?.candidates
    }

    func archiveEvents(sourceRoot: String, archiveRoot: String, eventFolders: [String]) async -> ArchiveRunResult? {
        struct Payload: Codable { let sourceRoot: String; let archiveRoot: String; let eventFolders: [String] }
        var result: ArchiveRunResult?
        await perform(showSuccess: false) {
            result = try await self.request(
                "archive_events",
                payload: Payload(sourceRoot: sourceRoot, archiveRoot: archiveRoot, eventFolders: eventFolders)
            )
        }
        return result
    }

    private func request<Payload: Encodable, Result: Decodable>(
        _ command: String,
        payload: Payload
    ) async throws -> Result {
        guard let client else {
            throw BackendError.unavailable("The Python backend is unavailable. Set ECC_BACKEND_ROOT and ECC_PYTHON, then restart the app.")
        }
        return try await client.request(command, payload: payload)
    }


    private func perform(showSuccess: Bool, _ operation: @escaping () async throws -> Void) async {
        isWorking = true
        defer { isWorking = false }
        do {
            try await operation()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
