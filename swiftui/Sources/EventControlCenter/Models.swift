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

struct MediaSessionInfo: Codable, Identifiable {
    let index: Int
    let startTime: String
    let endTime: String
    let photoCount: Int
    let videoCount: Int
    let fileCount: Int

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

struct ImportMediaPayload: Codable {
    let source: String
    let eventFolder: String
    let sessionGapMinutes: Int
    let sessionIndexes: [Int]
    let eventName: String
}

struct ImportOutcome: Codable {
    let photosImported: Int
    let videosImported: Int
    let skipped: Int
    let failed: Int
    let jpgsGenerated: Int
    let failures: [String]
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
}

struct JPGResult: Codable {
    let generated: Int
    let skipped: Int
    let failed: Int
    let cancelled: Bool
    let failures: [String]
}

struct CountResult: Codable {
    let found: Int
    let updated: Int
    let unchanged: Int
    let failed: Int
    let failures: [String]
}
