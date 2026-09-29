import Foundation

enum AppSection: String, CaseIterable, Identifiable {
    case `import` = "Import"
    case search = "Search"
    case utilities = "Utilities"
    case metadata = "Metadata"
    case settings = "Settings"

    var id: String { rawValue }

    var symbol: String {
        switch self {
        case .import: "square.and.arrow.down"
        case .search: "magnifyingglass"
        case .utilities: "wand.and.stars"
        case .metadata: "doc.text"
        case .settings: "gearshape"
        }
    }
}

enum ImportDestination: String, CaseIterable, Identifiable, Codable {
    case googleDrive = "Google Drive"
    case local = "Local Events Folder"

    var id: String { rawValue }
}

struct BackendEnvelope<Value: Decodable>: Decodable {
    let ok: Bool
    let data: Value?
    let error: String?
}

struct ConfigSnapshot: Codable {
    let defaultEventYear: String
    let defaultSchoolYear: String
    let eventRoot: String
    let localEventRoot: String
    let multimediaEventsRoot: String
    let localEventsRoot: String
    let googleSheetsCredentialsFile: String
    let googleSheetsSpreadsheetId: String
    let googleSheetsWorksheetName: String
    let lightroomTemplateDir: String
    let premiereTemplate: String
}

struct CreateEventPayload: Codable {
    let eventName: String
    let eventDate: String
    let destination: String
    let schoolYear: String
    let description: String
    let keywords: [String]
    let grades: [String]
    let allowOverwrite: Bool
}

struct CreatedEvent: Codable {
    let eventFolder: String
    let alreadyExisted: Bool
}

struct ExistingEventInfo: Codable {
    let eventFolder: String
    let eventName: String
    let eventDate: String
}

struct MediaSessionInfo: Codable, Identifiable {
    let index: Int
    let startTime: String
    let endTime: String
    let photoCount: Int
    let videoCount: Int
    let fileCount: Int
    let startThumbnail: String?
    let endThumbnail: String?

    var id: Int { index }
}

struct MediaScan: Codable {
    let source: String
    let photoCount: Int
    let videoCount: Int
    let skippedCount: Int
    let failures: [String]
    let sessions: [MediaSessionInfo]
}

struct ImportSourceInfo: Codable, Identifiable, Hashable {
    let name: String
    let path: String
    let isRemovable: Bool

    var id: String { path }
}

struct ImportSourcesResponse: Codable {
    let sources: [ImportSourceInfo]
}

struct ImportMediaPayload: Codable {
    let source: String
    let eventFolder: String
    let sessionGapMinutes: Int
    let sessionIndexes: [Int]
    let eventName: String
    let brightness: Int
}

struct ImportOutcome: Codable {
    let source: String
    let photosImported: Int
    let videosImported: Int
    let skipped: Int
    let failed: Int
    let jpgsGenerated: Int
    let failures: [String]
    let importedSources: [String]
}

struct ImportStreamEvent: Codable {
    let type: String
    let current: Int?
    let total: Int?
    let currentFile: String?
    let message: String?
    let currentBytes: Int?
    let totalBytes: Int?
    let bytesPerSecond: Double?
    let phase: String?
    let overallCompleted: Double?
    let overallTotal: Double?
    let outcome: ImportOutcome?
    let error: String?
}

struct SourceCleanupPayload: Codable {
    let source: String
    let files: [String]
}

struct SourceCleanupResult: Codable {
    let deleted: Int
    let deleteFailures: [String]
    let ejected: Bool
    let ejectMessage: String
}

struct SearchIndex: Codable {
    let records: [EventRecord]
    let suggestions: [String]
    let schoolYears: [String]
    let grades: [String]
    let keywords: [String]
    let errors: [String]
}

struct EventRecord: Codable, Identifiable, Hashable {
    let eventFolder: String
    let sourceName: String
    let eventName: String
    let date: String
    let schoolYear: String
    let grades: [String]
    let keywords: [String]
    let description: String
    let photoCount: Int
    let videoCount: Int
    let uneditedJpgCount: Int
    let lastModified: String

    var id: String { eventFolder }
    var displayName: String { eventName.isEmpty ? URL(fileURLWithPath: eventFolder).lastPathComponent : eventName }
}

struct SettingsPayload: Codable {
    let multimediaEventsRoot: String
    let localEventsRoot: String
    let defaultEventYear: String
    let googleSheetsCredentialsFile: String
    let googleSheetsSpreadsheetId: String
    let googleSheetsWorksheetName: String
    let lightroomTemplateDir: String
    let premiereTemplate: String
}

struct JPGResult: Codable {
    let generated: Int
    let skipped: Int
    let failed: Int
    let cancelled: Bool
    let failures: [String]
}

struct JPGStreamEvent: Codable {
    let type: String
    let current: Int?
    let total: Int?
    let currentFile: String?
    let message: String?
    let result: JPGResult?
    let error: String?
}

struct CountResult: Codable {
    let found: Int
    let updated: Int
    let unchanged: Int
    let failed: Int
    let failures: [String]
}

struct GoogleSheetsSyncResult: Codable {
    let found: Int
    let synced: Int
    let partial: Int
    let failed: Int
    let failures: [String]
}

struct ArchiveCandidate: Codable, Identifiable, Hashable {
    let source: String
    let year: String
    let name: String
    let destination: String
    let alreadyArchived: Bool
    let destinationExists: Bool

    var id: String { source }
    var isReadyToArchive: Bool { !alreadyArchived && !destinationExists }
    var availabilityLabel: String {
        if alreadyArchived { return "Already archived" }
        if destinationExists { return "Already on shared drive" }
        return "Ready to archive"
    }
}

struct ArchiveCandidatesResponse: Codable {
    let candidates: [ArchiveCandidate]
}

struct ArchiveResultItem: Codable, Identifiable {
    let source: String
    let destination: String
    let status: String
    let message: String

    var id: String { source }
}

struct ArchiveRunResult: Codable {
    let sourceRoot: String
    let archiveRoot: String
    let selected: Int
    let moved: Int
    let skipped: Int
    let failed: Int
    let results: [ArchiveResultItem]
}
