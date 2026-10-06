import AppKit
import Sparkle
import SwiftUI
import UserNotifications

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
        .commands {
            CommandGroup(after: .appInfo) {
                Button("Check for Updates…") { appDelegate.checkForUpdates() }
            }
        }
    }
}

final class EventControlCenterDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    private var updaterController: SPUStandardUpdaterController?

    func checkForUpdates() {
        updaterController?.checkForUpdates(nil)
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        if Bundle.main.bundleURL.pathExtension == "app",
           Bundle.main.bundleIdentifier != "jp.ac.enishi.event-control-center.hero-test",
           Bundle.main.bundleIdentifier != nil {
            UNUserNotificationCenter.current().delegate = self
            let controller = SPUStandardUpdaterController(
                startingUpdater: true,
                updaterDelegate: nil,
                userDriverDelegate: nil
            )
            updaterController = controller
            if controller.updater.automaticallyChecksForUpdates {
                controller.updater.checkForUpdatesInBackground()
            }
        }
        DispatchQueue.main.async {
            NSApp.activate(ignoringOtherApps: true)
        }
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .sound])
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

    func keywordVocabulary() async -> [KeywordSuggestion] {
        do {
            let result: KeywordVocabularyResponse = try await request("keyword_vocabulary", payload: EmptyPayload())
            return result.entries
        } catch {
            errorMessage = error.localizedDescription
            return []
        }
    }

    func inspectExistingEvent(folder: String) async -> ExistingEventInfo? {
        struct Payload: Codable { let eventFolder: String }
        var result: ExistingEventInfo?
        await perform(showSuccess: false) {
            result = try await self.request(
                "inspect_existing_event", payload: Payload(eventFolder: folder)
            )
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

    func notifyCardSafety(title: String, message: String) {
        sendNotification(title: title, message: message, prefix: "card-safety")
    }

    func notifyImportFinished(eventName: String, outcome: ImportOutcome) {
        let issueCount = outcome.failures.count
        let title = issueCount == 0 ? "Import complete" : "Import finished with issues"
        let summary = "\(outcome.photosImported) photos and \(outcome.videosImported) videos imported."
        let issueText = issueCount == 0 ? "" : " \(issueCount) issue(s) need review."
        sendNotification(
            title: title,
            message: "\(eventName): \(summary)\(issueText)",
            prefix: "import-finished"
        )
    }

    private func sendNotification(title: String, message: String, prefix: String) {
        // `swift run` launches a bare executable, not an application bundle.
        // UserNotifications raises an Objective-C exception (which Swift cannot
        // catch) if asked for the current center without a bundle proxy.
        guard Bundle.main.bundleURL.pathExtension == "app",
              Bundle.main.bundleIdentifier != nil else {
            return
        }

        Task {
            let center = UNUserNotificationCenter.current()
            let settings = await center.notificationSettings()
            let authorization: UNAuthorizationStatus

            if settings.authorizationStatus == .notDetermined {
                let granted = (try? await center.requestAuthorization(options: [.alert, .sound])) ?? false
                authorization = granted ? .authorized : .denied
            } else {
                authorization = settings.authorizationStatus
            }

            guard authorization == .authorized || authorization == .provisional else { return }

            let content = UNMutableNotificationContent()
            content.title = title
            content.body = message
            content.sound = .default
            try? await center.add(
                UNNotificationRequest(
                    identifier: "\(prefix)-\(UUID().uuidString)",
                    content: content,
                    trigger: nil
                )
            )
        }
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

    func heroList() async -> [HeroAsset]? {
        var result: HeroAssetsResponse?
        await perform(showSuccess: false) {
            result = try await self.request("hero_list", payload: EmptyPayload())
        }
        return result?.assets
    }

    func heroScan() async -> HeroScanResponse? {
        var result: HeroScanResponse?
        await perform(showSuccess: false) {
            result = try await self.request("hero_scan", payload: EmptyPayload())
        }
        return result
    }

    func heroRefresh(limit: Int? = nil) async -> HeroRefreshResponse? {
        struct Payload: Codable { let limit: Int? }
        var result: HeroRefreshResponse?
        await perform(showSuccess: false) {
            result = try await self.request("hero_refresh", payload: Payload(limit: limit))
        }
        return result
    }

    func heroWorkspace() async -> HeroWorkspaceResponse? {
        var result: HeroWorkspaceResponse?
        await perform(showSuccess: false) {
            result = try await self.request("hero_workspace", payload: EmptyPayload())
        }
        return result
    }

    func heroRemove(ids: [String]) async -> [HeroAsset]? {
        var result: HeroAssetsResponse?
        await perform(showSuccess: false) {
            result = try await self.request("hero_remove", payload: HeroIDsPayload(assetIds: ids))
        }
        return result?.assets
    }

    func heroRestore(ids: [String]) async -> [HeroAsset]? {
        var result: HeroAssetsResponse?
        await perform(showSuccess: false) {
            result = try await self.request("hero_restore", payload: HeroIDsPayload(assetIds: ids))
        }
        return result?.assets
    }

    func heroUpdate(ids: [String], changes: [String: HeroValue]) async -> HeroUpdateResponse? {
        var result: HeroUpdateResponse?
        await perform(showSuccess: false) {
            result = try await self.request("hero_update", payload: HeroChangesPayload(assetIds: ids, changes: changes))
        }
        return result
    }

    func heroStage(ids: [String]) async -> [HeroAsset]? {
        var result: HeroAssetsResponse?
        await perform(showSuccess: false) {
            result = try await self.request("hero_stage", payload: HeroIDsPayload(assetIds: ids))
        }
        return result?.assets
    }

    func heroMatchExports() async -> HeroMatchResponse? {
        var result: HeroMatchResponse?
        await perform(showSuccess: false) {
            result = try await self.request("hero_match_exports", payload: EmptyPayload())
        }
        return result
    }

    func heroPublish(ids: [String]) async -> [HeroAsset]? {
        var result: HeroAssetsResponse?
        await perform(showSuccess: false) {
            result = try await self.request("hero_publish", payload: HeroIDsPayload(assetIds: ids))
        }
        return result?.assets
    }

    func heroPushBatch(ids: [String]) async -> HeroPushResponse? {
        var result: HeroPushResponse?
        await perform(showSuccess: false) {
            result = try await self.request("hero_push_batch", payload: HeroIDsPayload(assetIds: ids))
        }
        return result
    }

    func heroPushOriginals(ids: [String]) async -> HeroPushResponse? {
        var result: HeroPushResponse?
        await perform(showSuccess: false) {
            result = try await self.request("hero_push_originals", payload: HeroIDsPayload(assetIds: ids))
        }
        return result
    }

    func heroRenamePublished() async -> HeroRenameResponse? {
        var result: HeroRenameResponse?
        await perform(showSuccess: false) {
            result = try await self.request("hero_rename_published", payload: EmptyPayload())
        }
        return result
    }

    func heroReorganize() async -> HeroReorganizeResponse? {
        var result: HeroReorganizeResponse?
        await perform(showSuccess: false) {
            result = try await self.request("hero_reorganize", payload: EmptyPayload())
        }
        return result
    }

    func heroAuditDrive() async -> HeroDriveAuditResponse? {
        var result: HeroDriveAuditResponse?
        await perform(showSuccess: false) {
            result = try await self.request("hero_audit_drive", payload: EmptyPayload())
        }
        return result
    }

    func heroAdoptDrive(path: String) async -> HeroDriveAdoptResponse? {
        struct Payload: Codable { let paths: [String] }
        var result: HeroDriveAdoptResponse?
        await perform(showSuccess: false) {
            result = try await self.request("hero_adopt_drive", payload: Payload(paths: [path]))
        }
        return result
    }

    func heroSaveSettings(_ payload: HeroSettingsPayload) async {
        await perform(showSuccess: false) {
            let config: ConfigSnapshot = try await self.request("hero_save_settings", payload: payload)
            self.configuration = config
            self.notice = "Hero Library locations saved."
        }
    }

    func generateJPGs(
        folder: String,
        regenerateAll: Bool,
        brightness: Int,
        onProgress: @escaping (JPGStreamEvent) -> Void
    ) async -> JPGResult? {
        struct Payload: Codable { let eventFolder: String; let regenerateAll: Bool; let brightness: Int }
        guard let client else {
            errorMessage = "The Python backend is unavailable."
            return nil
        }

        isWorking = true
        defer { isWorking = false }
        do {
            let events = try client.jpgEvents(
                payload: Payload(eventFolder: folder, regenerateAll: regenerateAll, brightness: brightness)
            )
            var result: JPGResult?
            for try await event in events {
                if event.type == "progress" {
                    onProgress(event)
                } else if event.type == "error" {
                    throw BackendError.failed(event.error ?? "JPG generation failed.")
                } else if event.type == "completed" {
                    result = event.result
                }
            }
            guard let result else {
                throw BackendError.failed("JPG generation stopped before returning a summary.")
            }
            return result
        } catch {
            errorMessage = error.localizedDescription
            return nil
        }
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
