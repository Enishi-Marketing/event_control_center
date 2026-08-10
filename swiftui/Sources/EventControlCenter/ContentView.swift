import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @State private var selection: AppSection? = .import
    @EnvironmentObject private var app: AppState

    var body: some View {
        NavigationSplitView {
            List(AppSection.allCases, selection: $selection) { section in
                Label(section.rawValue, systemImage: section.symbol)
                    .tag(section)
            }
            .listStyle(.sidebar)
            .navigationTitle("Control Center")
        } detail: {
            Group {
                switch selection ?? .import {
                case .import: ImportView()
                case .search: SearchView()
                case .utilities: UtilitiesView()
                case .metadata: MetadataView()
                case .settings: SettingsView()
                }
            }
            .frame(minWidth: 780)
            .overlay(alignment: .bottom) {
                if let notice = app.notice {
                    Label(notice, systemImage: "checkmark.circle.fill")
                        .font(.subheadline)
                        .padding(.horizontal, 14).padding(.vertical, 10)
                        .background(.regularMaterial, in: Capsule())
                        .padding(20)
                }
            }
        }
        .alert("Event Control Center", isPresented: Binding(
            get: { app.errorMessage != nil },
            set: { if !$0 { app.errorMessage = nil } }
        )) {
            Button("OK", role: .cancel) { app.errorMessage = nil }
        } message: {
            Text(app.errorMessage ?? "")
        }
    }
}

private struct PageHeader: View {
    let title: String
    let subtitle: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.system(size: 30, weight: .bold, design: .rounded))
            Text(subtitle).foregroundStyle(.secondary)
        }
    }
}

private struct Card<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        content
            .padding(20)
            .background(Color(nsColor: .windowBackgroundColor).opacity(0.72), in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .stroke(.white.opacity(0.08))
                    .allowsHitTesting(false)
            )
    }
}

struct ImportView: View {
    @EnvironmentObject private var app: AppState
    @State private var eventName = ""
    @State private var eventDate = Date()
    @State private var destination: ImportDestination = .googleDrive
    @State private var schoolYear = ""
    @State private var description = ""
    @State private var keywords: [String] = []
    @State private var selectedGrades: Set<String> = []
    @State private var currentFolder: String?
    @State private var sourcePath = ""
    @State private var detectedSources: [ImportSourceInfo] = []
    @State private var selectedDetectedSourcePath = ""
    @State private var sessionGap = 20
    @State private var scan: MediaScan?
    @State private var isScanning = false
    @State private var selectedSessions: Set<Int> = []
    @State private var isImporting = false
    @State private var importProgress: ImportStreamEvent?
    @State private var importStartedAt: Date?
    @State private var pendingSourceCleanup: ImportOutcome?
    @State private var isCleaningUpSource = false
    @State private var cardSafetyMessage: String?
    @State private var cardIsSafeToRemove = false
    @State private var choosingSource = false
    @State private var replaceExisting = false

    private let gradeGroups = [
        ("School-wide", ["All", "Staff", "Parents"]),
        ("School Sections", ["ELC", "PYP", "MYP", "DP"]),
        ("Early Years", ["Foundation", "Preschool", "PreK", "Kindergarten"]),
        ("Year Levels", (1...12).map { "Grade \($0)" }),
    ]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                PageHeader(title: "Import media", subtitle: "Prepare an event, review camera sessions, and bring in verified files.")
                eventCard
                sourceCard
                if isScanning { MediaScanProgressPanel() }
                if let scan { scanCard(scan) }
                if let folder = currentFolder {
                    Label("Event folder ready: \(folder)", systemImage: "checkmark.circle.fill")
                        .font(.subheadline).foregroundStyle(.green)
                }
            }
            .padding(28)
            .frame(maxWidth: 1120, alignment: .leading)
        }
        .fileImporter(isPresented: $choosingSource, allowedContentTypes: [.folder]) { result in
            if case .success(let url) = result {
                sourcePath = url.path
                scan = nil
                clearCardSafetyStatus()
            }
        }
        .onChange(of: app.configuration?.defaultSchoolYear) { _, _ in
            applyDefaultSchoolYear()
        }
        .task {
            applyDefaultSchoolYear()
            await monitorRemovableMedia()
        }
        .onChange(of: sourcePath) { _, path in
            if !path.isEmpty && !isCleaningUpSource {
                clearCardSafetyStatus()
            }
        }
        .alert(
            "Delete verified imported media and eject the card?",
            isPresented: Binding(
                get: { pendingSourceCleanup != nil },
                set: { if !$0 { pendingSourceCleanup = nil } }
            )
        ) {
            Button("Keep media", role: .cancel) { pendingSourceCleanup = nil }
            Button("Delete and eject", role: .destructive) {
                Task { await cleanUpImportedMedia() }
            }
        } message: {
            let imported = pendingSourceCleanup?.importedSources.count ?? 0
            let failed = pendingSourceCleanup?.failed ?? 0
            Text(
                "Only the \(imported) file(s) copied and verified during this import will be deleted."
                    + (failed > 0 ? " \(failed) failed file(s) will stay on the card." : "")
            )
        }
    }

    private var eventCard: some View {
        Card {
            VStack(alignment: .leading, spacing: 16) {
                Label("Event details", systemImage: "calendar.badge.plus").font(.headline)
                HStack(alignment: .top, spacing: 16) {
                    TextField("Event name", text: $eventName).textFieldStyle(.roundedBorder)
                    DatePicker("Date", selection: $eventDate, displayedComponents: .date).labelsHidden().datePickerStyle(.compact)
                    Picker("Destination", selection: $destination) {
                        ForEach(ImportDestination.allCases) { Text($0.rawValue).tag($0) }
                    }.pickerStyle(.menu).frame(width: 180)
                }
                TextField("School year", text: $schoolYear).textFieldStyle(.roundedBorder)
                TagEditor(tags: $keywords)
                VStack(alignment: .leading, spacing: 6) {
                    Text("Description")
                        .font(.subheadline.weight(.medium))
                    TextEditor(text: $description)
                        .font(.body)
                        .frame(height: 84)
                        .scrollContentBackground(.hidden)
                        .padding(8)
                        .background(.black.opacity(0.22), in: RoundedRectangle(cornerRadius: 10))
                        .overlay(alignment: .topLeading) {
                            if description.isEmpty {
                                Text("Add an optional description")
                                    .foregroundStyle(.tertiary)
                                    .padding(.horizontal, 13)
                                    .padding(.vertical, 14)
                                    .allowsHitTesting(false)
                            }
                        }
                        .accessibilityLabel("Description")
                }
                Divider()
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 135), spacing: 8)], spacing: 8) {
                    ForEach(Array(gradeGroups.enumerated()), id: \.offset) { _, group in
                        Menu {
                            ForEach(group.1, id: \.self) { grade in
                                Toggle(grade, isOn: Binding(
                                    get: { selectedGrades.contains(grade) },
                                    set: { isSelected in
                                        if isSelected {
                                            selectedGrades.insert(grade)
                                        } else {
                                            selectedGrades.remove(grade)
                                        }
                                    }
                                ))
                            }
                        } label: {
                            Label(group.0, systemImage: "checklist")
                        }
                        .menuStyle(.borderedButton)
                    }
                }
                HStack {
                    Toggle("Replace metadata if this event already exists", isOn: $replaceExisting).font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Button {
                        Task { await createEvent() }
                    } label: { Label("Create event", systemImage: "folder.badge.plus") }
                    .buttonStyle(.borderedProminent).disabled(eventName.trimmingCharacters(in: .whitespaces).isEmpty || app.isWorking)
                }
            }
        }
    }

    private var sourceCard: some View {
        Card {
            VStack(alignment: .leading, spacing: 14) {
                Label("Import source", systemImage: "externaldrive.fill").font(.headline)
                if detectedSources.isEmpty {
                    Text("Watching for an SD card or other removable media…")
                        .font(.caption).foregroundStyle(.secondary)
                } else {
                    Picker("Detected media", selection: $selectedDetectedSourcePath) {
                        Text("Select detected media").tag("")
                        ForEach(detectedSources) { source in
                            Text(source.name).tag(source.path)
                        }
                    }
                    .onChange(of: selectedDetectedSourcePath) { _, path in
                        guard !path.isEmpty else { return }
                        sourcePath = path
                        scan = nil
                        clearCardSafetyStatus()
                    }
                }
                HStack {
                    Text(sourcePath.isEmpty ? "Choose an SD card or media folder." : sourcePath).lineLimit(1).foregroundStyle(sourcePath.isEmpty ? .secondary : .primary)
                    Spacer()
                    Button("Choose folder") { choosingSource = true }
                }
                HStack {
                    Stepper("Session gap: \(sessionGap) minutes", value: $sessionGap, in: 1...120).frame(maxWidth: 260)
                    Spacer()
                    Button { Task { await scanMedia() } } label: { Label("Scan media", systemImage: "viewfinder") }
                        .buttonStyle(.bordered).disabled(sourcePath.isEmpty || app.isWorking || isScanning || isCleaningUpSource)
                }
                if isCleaningUpSource {
                    CardSafetyPanel(
                        title: "Cleaning up card — do not pull it",
                        message: "Deleting verified files and asking macOS to eject the card…",
                        isSafe: false,
                        isWorking: true
                    )
                } else if let cardSafetyMessage {
                    CardSafetyPanel(
                        title: cardIsSafeToRemove ? "Safe to pull card" : "Card is not safe to pull",
                        message: cardSafetyMessage,
                        isSafe: cardIsSafeToRemove,
                        isWorking: false
                    )
                }
            }
        }
    }

    private func scanCard(_ scan: MediaScan) -> some View {
        Card {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Label("Media sessions", systemImage: "rectangle.stack.badge.play").font(.headline)
                    Spacer()
                    Text("\(scan.photoCount) photos · \(scan.videoCount) videos").foregroundStyle(.secondary)
                }
                ForEach(scan.sessions) { session in
                    SessionRow(session: session, selectedSessions: $selectedSessions)
                }
                if isImporting {
                    ImportProgressPanel(
                        progress: importProgress,
                        startedAt: importStartedAt ?? Date()
                    )
                }
                HStack {
                    Button("Select all") { selectedSessions = Set(scan.sessions.map(\.index)) }.buttonStyle(.link)
                    Button("Select none") { selectedSessions = [] }.buttonStyle(.link)
                    Spacer()
                    Button { Task { await importSelected() } } label: { Label("Import selected media", systemImage: "square.and.arrow.down.fill") }
                        .buttonStyle(.borderedProminent).disabled(currentFolder == nil || selectedSessions.isEmpty || app.isWorking || isImporting)
                }
                if currentFolder == nil { Text("Create the event first to enable importing.").font(.caption).foregroundStyle(.orange) }
            }
        }
    }

    private func createEvent() async {
        let date = DateFormatter.eventDate.string(from: eventDate)
        let payload = CreateEventPayload(eventName: eventName, eventDate: date, destination: destination.rawValue, schoolYear: schoolYear, description: description, keywords: keywords, grades: selectedGrades.sorted(), allowOverwrite: replaceExisting)
        if let result = await app.createEvent(payload) {
            currentFolder = result.eventFolder
            app.notice = result.alreadyExisted ? "Event metadata was updated." : "Event created and ready for media."
        }
    }

    private func scanMedia() async {
        guard !isScanning, !sourcePath.isEmpty else { return }
        isScanning = true
        defer { isScanning = false }
        if let value = await app.scan(source: sourcePath, gap: sessionGap) {
            scan = value; selectedSessions = Set(value.sessions.map(\.index))
        }
    }

    private func applyDefaultSchoolYear() {
        guard schoolYear.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              let defaultYear = app.configuration?.defaultSchoolYear.trimmingCharacters(in: .whitespacesAndNewlines),
              !defaultYear.isEmpty else {
            return
        }
        schoolYear = defaultYear
    }

    private func monitorRemovableMedia() async {
        while !Task.isCancelled {
            let sources = await app.availableSources()
            let previousPaths = Set(detectedSources.map(\.path))
            detectedSources = sources

            let selectedSourceStillAvailable = sources.contains {
                $0.path == selectedDetectedSourcePath
            }
            if let firstSource = sources.first,
               sourcePath.isEmpty || (!selectedDetectedSourcePath.isEmpty && !selectedSourceStillAvailable) {
                sourcePath = firstSource.path
                selectedDetectedSourcePath = firstSource.path
                scan = nil
                clearCardSafetyStatus()
                if !previousPaths.contains(firstSource.path) {
                    app.notice = "Detected \(firstSource.name). Ready to scan media."
                    if !isImporting && !isScanning {
                        Task { await scanMedia() }
                    }
                }
            }

            try? await Task.sleep(nanoseconds: 2_000_000_000)
        }
    }

    private func importSelected() async {
        guard let currentFolder else { return }
        let payload = ImportMediaPayload(source: sourcePath, eventFolder: currentFolder, sessionGapMinutes: sessionGap, sessionIndexes: selectedSessions.sorted(), eventName: eventName)
        isImporting = true
        importStartedAt = Date()
        importProgress = ImportStreamEvent(
            type: "progress",
            current: 0,
            total: selectedSessions.count,
            currentFile: nil,
            message: "Preparing import…",
            currentBytes: 0,
            totalBytes: 0,
            bytesPerSecond: 0,
            phase: "Preparing",
            overallCompleted: 0,
            overallTotal: Double(selectedSessions.count),
            outcome: nil,
            error: nil
        )
        defer { isImporting = false }
        if let outcome = await app.importMedia(payload, onProgress: { event in
            importProgress = event
        }) {
            app.notice = "Imported \(outcome.photosImported) photos and \(outcome.videosImported) videos. Generated \(outcome.jpgsGenerated) JPGs."
            if !outcome.importedSources.isEmpty {
                pendingSourceCleanup = outcome
            }
        }
    }

    private func cleanUpImportedMedia() async {
        guard let outcome = pendingSourceCleanup else { return }
        pendingSourceCleanup = nil
        isCleaningUpSource = true
        cardSafetyMessage = nil
        cardIsSafeToRemove = false
        defer { isCleaningUpSource = false }
        let cleanup = SourceCleanupPayload(source: sourcePath, files: outcome.importedSources)
        if let result = await app.cleanupImportedMedia(cleanup) {
            if result.ejected {
                let failures = result.deleteFailures.count
                cardIsSafeToRemove = true
                cardSafetyMessage = failures == 0
                    ? "The card was ejected. It is safe to pull."
                    : "The card was ejected and is safe to pull. \(failures) file(s) could not be deleted."
                app.notice = "Deleted \(result.deleted) verified file(s) and ejected the card."
                sourcePath = ""
                selectedDetectedSourcePath = ""
                scan = nil
            } else {
                let message = result.ejectMessage.isEmpty ? "The source was not ejected." : result.ejectMessage
                cardIsSafeToRemove = false
                cardSafetyMessage = "macOS did not eject the card. Do not pull it yet. \(message)"
                app.notice = "Deleted \(result.deleted) verified file(s). \(message)"
            }
        } else {
            cardIsSafeToRemove = false
            cardSafetyMessage = "Cleanup did not finish. Do not pull the card; check the error message and try again."
        }
    }

    private func clearCardSafetyStatus() {
        guard !isCleaningUpSource else { return }
        cardSafetyMessage = nil
        cardIsSafeToRemove = false
    }
}

private struct CardSafetyPanel: View {
    let title: String
    let message: String
    let isSafe: Bool
    let isWorking: Bool

    private var tint: Color { isWorking ? .orange : (isSafe ? .green : .red) }

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            if isWorking {
                ProgressView().controlSize(.small).tint(tint)
            } else {
                Image(systemName: isSafe ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                    .foregroundStyle(tint)
            }
            VStack(alignment: .leading, spacing: 4) {
                Text(title).fontWeight(.semibold)
                Text(message).font(.caption).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
        .padding(12)
        .background(tint.opacity(0.12), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(tint.opacity(0.45))
                .allowsHitTesting(false)
        )
    }
}

private struct MediaScanProgressPanel: View {
    var body: some View {
        HStack(spacing: 12) {
            ProgressView().controlSize(.small)
            VStack(alignment: .leading, spacing: 6) {
                Text("Scanning media").fontWeight(.semibold)
                ProgressView().tint(.cyan)
                Text("Reading the card and grouping files into capture sessions…")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(14)
        .background(.cyan.opacity(0.08), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(.cyan.opacity(0.3))
                .allowsHitTesting(false)
        )
    }
}

private struct ImportProgressPanel: View {
    let progress: ImportStreamEvent?
    let startedAt: Date

    private var current: Int { progress?.current ?? 0 }
    private var total: Int { max(progress?.total ?? 0, 1) }
    private var overallValue: Double {
        if let completed = progress?.overallCompleted,
           let total = progress?.overallTotal,
           total > 0 {
            return min(max(completed / total, 0), 1)
        }
        let completedFiles = Double(max(current - 1, 0))
        let currentFilePortion = currentFileValue
            ?? (progress?.phase == "Generating previews" ? 1 : 0)
        return min(max((completedFiles + currentFilePortion) / Double(total), 0), 1)
    }
    private var currentFileValue: Double? {
        guard let copied = progress?.currentBytes,
              let size = progress?.totalBytes,
              size > 0 else { return nil }
        return min(max(Double(copied) / Double(size), 0), 1)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Text(progress?.phase?.isEmpty == false ? progress?.phase ?? "Importing" : "Importing media")
                    .fontWeight(.semibold)
                Spacer()
                Text(remainingTimeText).monospacedDigit().foregroundStyle(.secondary)
            }
            ProgressView(value: overallValue)
                .tint(.cyan)
            HStack {
                Text("\(min(current, total)) of \(total) files")
                Spacer()
                if let speed = progress?.bytesPerSecond, speed > 0 {
                    Text("\(ByteCountFormatter.string(fromByteCount: Int64(speed), countStyle: .file))/s")
                }
            }
            .font(.caption).foregroundStyle(.secondary)
            if let currentFileValue {
                ProgressView(value: currentFileValue).tint(.blue)
                HStack {
                    Text(progress?.currentFile.map { URL(fileURLWithPath: $0).lastPathComponent } ?? "Copying file")
                        .lineLimit(1)
                    Spacer()
                    Text(fileProgressText).monospacedDigit()
                }
                .font(.caption).foregroundStyle(.secondary)
            } else if let message = progress?.message, !message.isEmpty {
                Text(message).font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(14)
        .background(.cyan.opacity(0.08), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(.cyan.opacity(0.3))
                .allowsHitTesting(false)
        )
    }

    private var fileProgressText: String {
        guard let copied = progress?.currentBytes, let size = progress?.totalBytes else { return "" }
        return "\(ByteCountFormatter.string(fromByteCount: Int64(copied), countStyle: .file)) / \(ByteCountFormatter.string(fromByteCount: Int64(size), countStyle: .file))"
    }

    private var remainingTimeText: String {
        let fractionalFile = currentFileValue ?? 0
        let completed = Double(max(current - 1, 0)) + fractionalFile
        guard completed > 0.02 else { return "Estimating…" }
        let elapsed = Date().timeIntervalSince(startedAt)
        let remaining = elapsed / completed * (Double(total) - completed)
        guard remaining.isFinite, remaining > 1 else { return "Almost done" }
        return "About \(durationText(remaining)) left"
    }

    private func durationText(_ interval: TimeInterval) -> String {
        let formatter = DateComponentsFormatter()
        formatter.allowedUnits = interval >= 3600 ? [.hour, .minute] : [.minute, .second]
        formatter.unitsStyle = .abbreviated
        formatter.zeroFormattingBehavior = .dropAll
        return formatter.string(from: interval) ?? "a moment"
    }
}

private struct SessionRow: View {
    let session: MediaSessionInfo
    @Binding var selectedSessions: Set<Int>

    var body: some View {
        Toggle(isOn: Binding(
            get: { selectedSessions.contains(session.index) },
            set: { isSelected in
                if isSelected {
                    selectedSessions.insert(session.index)
                } else {
                    selectedSessions.remove(session.index)
                }
            }
        )) {
            HStack(spacing: 10) {
                HStack(spacing: 6) {
                    if let thumbnail = session.startThumbnail {
                        ThumbnailPreview(path: thumbnail)
                    }
                    if let thumbnail = session.endThumbnail, thumbnail != session.startThumbnail {
                        ThumbnailPreview(path: thumbnail)
                    }
                }
                VStack(alignment: .leading, spacing: 3) {
                    Text("Session \(session.index)").fontWeight(.semibold)
                    Text("\(time(session.startTime))–\(time(session.endTime)) · \(session.photoCount) photos · \(session.videoCount) videos")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
        }
        .toggleStyle(.checkbox)
        .padding(10)
        .background(.black.opacity(0.15), in: RoundedRectangle(cornerRadius: 10))
    }

    private func time(_ value: String) -> String {
        String(value.prefix(16)).replacingOccurrences(of: "T", with: " ")
    }
}

private struct ThumbnailPreview: View {
    let path: String

    var body: some View {
        Group {
            if let image = NSImage(contentsOf: URL(fileURLWithPath: path)) {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFill()
            } else {
                Image(systemName: "photo")
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(.black.opacity(0.25))
            }
        }
        .frame(width: 68, height: 48)
        .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 6, style: .continuous)
                .stroke(.white.opacity(0.9), lineWidth: 1)
                .allowsHitTesting(false)
        )
        .accessibilityLabel("Media preview")
    }
}

struct TagEditor: View {
    @Binding var tags: [String]
    @State private var draft = ""

    var body: some View {
        HStack(spacing: 6) {
            ForEach(tags, id: \.self) { tag in
                Text(tag).font(.caption).padding(.horizontal, 9).padding(.vertical, 5)
                    .background(.cyan.opacity(0.18), in: Capsule())
                    .overlay(alignment: .trailing) { EmptyView() }
                    .contextMenu { Button("Remove", role: .destructive) { tags.removeAll { $0 == tag } } }
            }
            TextField("Add keywords", text: $draft).textFieldStyle(.roundedBorder).onSubmit(addTags)
        }.onChange(of: draft) { _, text in if text.contains(",") { addTags() } }
    }

    private func addTags() {
        let additions = draft.split(separator: ",").map { $0.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() }.filter { !$0.isEmpty }
        tags = Array(Set(tags + additions)).sorted()
        draft = ""
    }
}

struct SearchView: View {
    @EnvironmentObject private var app: AppState
    @State private var index = SearchIndex(records: [], suggestions: [], schoolYears: [], grades: [], keywords: [], errors: [])
    @State private var query = ""
    @State private var source = "All event folders"
    @State private var grade = "All grades"
    @State private var keyword = "All keywords"
    @State private var selected: EventRecord?

    private var filtered: [EventRecord] {
        index.records.filter { record in
            let matchesQuery = query.isEmpty || [record.displayName, record.date, record.description, record.grades.joined(separator: " "), record.keywords.joined(separator: " ")].joined(separator: " ").localizedCaseInsensitiveContains(query)
            return matchesQuery && (grade == "All grades" || record.grades.contains(grade)) && (keyword == "All keywords" || record.keywords.contains(keyword))
        }.sorted { $0.date > $1.date }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeader(title: "Find events", subtitle: "Search every indexed metadata file across your event folders.")
            Card {
                HStack(spacing: 12) {
                    TextField("Search name, date, grade, keyword…", text: $query).textFieldStyle(.roundedBorder)
                    Picker("Source", selection: $source) { ForEach(["All event folders", "Current year", "Google Drive", "Local Events"], id: \.self) { Text($0) } }.frame(width: 165)
                    Picker("Grade", selection: $grade) { ForEach(["All grades"] + index.grades, id: \.self) { Text($0) } }.frame(width: 135)
                    Picker("Keyword", selection: $keyword) { ForEach(["All keywords"] + index.keywords, id: \.self) { Text($0) } }.frame(width: 150)
                    Button { Task { await refresh() } } label: { Image(systemName: "arrow.clockwise") }.help("Refresh search index")
                }
            }
            HSplitView {
                List(filtered, selection: $selected) { record in
                    VStack(alignment: .leading, spacing: 5) {
                        HStack { Text(record.displayName).fontWeight(.semibold); Spacer(); Text(record.date).foregroundStyle(.secondary) }
                        Text("\(record.photoCount) photos · \(record.videoCount) videos · \(record.sourceName)").font(.caption).foregroundStyle(.secondary)
                    }.padding(.vertical, 4).tag(record)
                }.frame(minWidth: 430)
                VStack(alignment: .leading, spacing: 14) {
                    if let selected {
                        Text(selected.displayName).font(.title2.bold())
                        LabeledContent("Date", value: selected.date)
                        LabeledContent("School year", value: selected.schoolYear)
                        LabeledContent("Grades", value: selected.grades.joined(separator: ", "))
                        LabeledContent("Keywords", value: selected.keywords.joined(separator: ", "))
                        Text(selected.description.isEmpty ? "No description" : selected.description).foregroundStyle(.secondary)
                        Spacer()
                        Button("Open in Finder", systemImage: "folder") { NSWorkspace.shared.open(URL(fileURLWithPath: selected.eventFolder)) }.buttonStyle(.bordered)
                    } else {
                        ContentUnavailableView("No event selected", systemImage: "magnifyingglass", description: Text("Choose an event to inspect its metadata."))
                    }
                }.padding(20).frame(minWidth: 300, maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            }
            Text("Showing \(filtered.count) of \(index.records.count) events").font(.caption).foregroundStyle(.secondary)
        }
        .padding(28).task { await refresh() }
    }

    private func refresh() async {
        if let result = await app.search(source: source) {
            index = result
            selected = nil
            if !result.errors.isEmpty { app.notice = "Loaded events with \(result.errors.count) metadata warning(s)." }
        }
    }
}

struct UtilitiesView: View {
    @EnvironmentObject private var app: AppState
    @State private var eventFolder = ""
    @State private var selectingFolder = false
    @State private var choosingYearRoot = false
    @State private var yearRoot = ""
    @State private var sheetsRoot = ""
    @State private var choosingSheetsRoot = false
    @State private var confirmingSheetSync = false
    @State private var archiveSourceRoot = ""
    @State private var archiveDriveRoot = ""
    @State private var choosingArchiveSource = false
    @State private var choosingArchiveDrive = false
    @State private var archiveCandidates: [ArchiveCandidate] = []
    @State private var selectedArchiveCandidates: Set<String> = []
    @State private var confirmingArchive = false
    @State private var archiveSummary: ArchiveRunResult?
    @State private var archiveStatus = "Choose the local and shared-drive event folders."

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                PageHeader(title: "Utilities", subtitle: "Maintain derivative files and bring event metadata back into sync.")
                Card {
                    VStack(alignment: .leading, spacing: 14) {
                        Label("Unedited JPGs", systemImage: "photo.stack").font(.headline)
                        Text(eventFolder.isEmpty ? "Choose an event folder to generate JPG previews." : eventFolder).lineLimit(1).foregroundStyle(eventFolder.isEmpty ? .secondary : .primary)
                        HStack { Button("Choose event folder") { selectingFolder = true }; Spacer(); Button("Generate missing JPGs") { Task { await createJPGs(false) } }.buttonStyle(.borderedProminent).disabled(eventFolder.isEmpty || app.isWorking); Button("Regenerate all") { Task { await createJPGs(true) } }.disabled(eventFolder.isEmpty || app.isWorking) }
                    }
                }
                Card {
                    VStack(alignment: .leading, spacing: 14) {
                        Label("Metadata counts", systemImage: "number.circle").font(.headline)
                        Text(yearRoot.isEmpty ? (app.configuration?.eventRoot ?? "Choose a year folder.") : yearRoot).lineLimit(1).foregroundStyle(.secondary)
                        HStack { Button("Choose year folder") { choosingYearRoot = true }; Spacer(); Button("Count photos and videos") { Task { await refreshCounts() } }.buttonStyle(.borderedProminent).disabled((yearRoot.isEmpty && app.configuration == nil) || app.isWorking) }
                    }
                }
                Card {
                    VStack(alignment: .leading, spacing: 14) {
                        Label("Google Sheets sync", systemImage: "tablecells.badge.ellipsis").font(.headline)
                        Text(sheetsRoot.isEmpty ? (app.configuration?.eventRoot ?? "Choose an event root to sync.") : sheetsRoot)
                            .lineLimit(1).foregroundStyle(.secondary)
                        Text("Syncs every event metadata file in this folder to the configured Google Sheet.")
                            .font(.caption).foregroundStyle(.secondary)
                        HStack {
                            Button("Choose event root") { choosingSheetsRoot = true }
                            Spacer()
                            Button("Sync all events") { confirmingSheetSync = true }
                                .buttonStyle(.borderedProminent)
                                .disabled((sheetsRoot.isEmpty && app.configuration == nil) || app.isWorking)
                        }
                    }
                }
                archiveCard
            }.padding(28).frame(maxWidth: 1050, alignment: .leading)
        }
        .fileImporter(isPresented: $selectingFolder, allowedContentTypes: [.folder]) { if case .success(let url) = $0 { eventFolder = url.path } }
        .fileImporter(isPresented: $choosingYearRoot, allowedContentTypes: [.folder]) { if case .success(let url) = $0 { yearRoot = url.path } }
        .fileImporter(isPresented: $choosingSheetsRoot, allowedContentTypes: [.folder]) { if case .success(let url) = $0 { sheetsRoot = url.path } }
        .fileImporter(isPresented: $choosingArchiveSource, allowedContentTypes: [.folder]) {
            if case .success(let url) = $0 { archiveSourceRoot = url.path; Task { await loadArchiveCandidates() } }
        }
        .fileImporter(isPresented: $choosingArchiveDrive, allowedContentTypes: [.folder]) {
            if case .success(let url) = $0 { archiveDriveRoot = url.path; Task { await loadArchiveCandidates() } }
        }
        .alert("Sync all events to Google Sheets?", isPresented: $confirmingSheetSync) {
            Button("Cancel", role: .cancel) {}
            Button("Sync") { Task { await syncGoogleSheets() } }
        } message: {
            Text("This will update the configured Google Sheet with metadata from every event in the selected folder.")
        }
        .alert("Archive selected events?", isPresented: $confirmingArchive) {
            Button("Cancel", role: .cancel) {}
            Button("Archive", role: .destructive) { Task { await archiveSelectedEvents() } }
        } message: {
            Text("This moves \(selectedArchiveCandidates.count) selected local event folder(s) to the shared drive and leaves shortcuts in their original locations.")
        }
        .task { setArchiveDefaults() }
        .onChange(of: app.configuration?.localEventsRoot) { _, _ in setArchiveDefaults() }
    }

    private var archiveCard: some View {
        Card {
            VStack(alignment: .leading, spacing: 14) {
                Label("Archive local events", systemImage: "archivebox").font(.headline)
                Text("Move completed local events to the shared drive and leave a shortcut in place. Existing shared-drive folders are excluded.")
                    .font(.caption).foregroundStyle(.secondary)
                archiveLocationRow("Local Events", path: archiveSourceRoot, action: { choosingArchiveSource = true })
                archiveLocationRow("Shared drive Events", path: archiveDriveRoot, action: { choosingArchiveDrive = true })
                HStack {
                    Text("Available events").font(.subheadline.weight(.medium))
                    Spacer()
                    Button("Refresh") { Task { await loadArchiveCandidates() } }
                        .disabled(archiveSourceRoot.isEmpty || archiveDriveRoot.isEmpty || app.isWorking)
                }
                if archiveCandidates.isEmpty {
                    ContentUnavailableView(
                        "No dated event folders found",
                        systemImage: "archivebox",
                        description: Text(archiveStatus)
                    )
                        .frame(maxWidth: .infinity).padding(.vertical, 10)
                } else {
                    List(archiveCandidates, selection: $selectedArchiveCandidates) { candidate in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(candidate.name).fontWeight(.medium)
                            Text("\(candidate.year) → \(candidate.destination)").font(.caption).foregroundStyle(.secondary).lineLimit(1)
                            Label(
                                candidate.availabilityLabel,
                                systemImage: candidate.isReadyToArchive ? "checkmark.circle" : "info.circle"
                            )
                            .font(.caption)
                            .foregroundStyle(candidate.isReadyToArchive ? .green : .secondary)
                        }
                        .padding(.vertical, 3)
                        .opacity(candidate.isReadyToArchive ? 1 : 0.65)
                        .tag(candidate.id)
                        .disabled(!candidate.isReadyToArchive)
                    }
                    .frame(height: 190)
                }
                Text(archiveStatus).font(.caption).foregroundStyle(.secondary)
                if let archiveSummary {
                    Text("Last archive: \(archiveSummary.moved) moved · \(archiveSummary.skipped) skipped · \(archiveSummary.failed) failed")
                        .font(.caption).foregroundStyle(archiveSummary.failed == 0 ? Color.secondary : Color.orange)
                }
                HStack {
                    Button("Select all") { selectedArchiveCandidates = Set(archiveCandidates.filter(\.isReadyToArchive).map(\.id)) }.buttonStyle(.link)
                    Button("Select none") { selectedArchiveCandidates = [] }.buttonStyle(.link)
                    Spacer()
                    Button("Archive selected", systemImage: "archivebox.fill") { confirmingArchive = true }
                        .buttonStyle(.borderedProminent)
                        .disabled(selectedArchiveCandidates.isEmpty || app.isWorking)
                }
            }
        }
    }

    private func archiveLocationRow(_ label: String, path: String, action: @escaping () -> Void) -> some View {
        HStack {
            Text(label).foregroundStyle(.secondary).frame(width: 130, alignment: .leading)
            Text(path.isEmpty ? "Choose a folder" : path).lineLimit(1).foregroundStyle(path.isEmpty ? .secondary : .primary)
            Spacer()
            Button("Choose…", action: action)
        }
    }

    private func setArchiveDefaults() {
        guard let configuration = app.configuration else { return }
        if archiveSourceRoot.isEmpty { archiveSourceRoot = configuration.localEventsRoot }
        if archiveDriveRoot.isEmpty { archiveDriveRoot = configuration.multimediaEventsRoot }
        if archiveCandidates.isEmpty { Task { await loadArchiveCandidates() } }
    }

    private func loadArchiveCandidates() async {
        guard !archiveSourceRoot.isEmpty, !archiveDriveRoot.isEmpty else {
            archiveStatus = "Choose both event folders, then refresh."
            return
        }
        if let candidates = await app.archiveCandidates(sourceRoot: archiveSourceRoot, archiveRoot: archiveDriveRoot) {
            archiveCandidates = candidates
            selectedArchiveCandidates = Set(candidates.filter(\.isReadyToArchive).map(\.id))
            let ready = candidates.filter(\.isReadyToArchive).count
            let archived = candidates.filter(\.alreadyArchived).count
            let existing = candidates.filter { $0.destinationExists && !$0.alreadyArchived }.count
            archiveStatus = candidates.isEmpty
                ? "No folders beginning with a date (YYYY.MM.DD) were found in the selected Local Events folder."
                : "Found \(candidates.count) event folder(s): \(ready) ready, \(archived) already archived, \(existing) already on the shared drive."
        } else {
            archiveStatus = "Could not read the selected Local Events folder. Check the error message, then try Refresh again."
        }
    }

    private func archiveSelectedEvents() async {
        let folders = archiveCandidates
            .filter { $0.isReadyToArchive && selectedArchiveCandidates.contains($0.id) }
            .map(\.source)
        guard let result = await app.archiveEvents(sourceRoot: archiveSourceRoot, archiveRoot: archiveDriveRoot, eventFolders: folders) else { return }
        archiveSummary = result
        app.notice = "Archive complete: \(result.moved) moved, \(result.skipped) skipped, \(result.failed) failed."
        await loadArchiveCandidates()
    }

    private func createJPGs(_ regenerate: Bool) async {
        if let result = await app.generateJPGs(folder: eventFolder, regenerateAll: regenerate) {
            app.notice = "JPGs: \(result.generated) generated, \(result.skipped) unchanged, \(result.failed) failed."
        }
    }

    private func refreshCounts() async {
        let root = yearRoot.isEmpty ? app.configuration?.eventRoot ?? "" : yearRoot
        if let result = await app.updateMediaCounts(root: root) {
            app.notice = "Checked \(result.found) events: \(result.updated) metadata file(s) updated."
        }
    }

    private func syncGoogleSheets() async {
        let root = sheetsRoot.isEmpty ? app.configuration?.eventRoot ?? "" : sheetsRoot
        if let result = await app.syncGoogleSheets(root: root) {
            app.notice = "Google Sheets: \(result.synced) synced, \(result.partial) partial, \(result.failed) failed."
            if !result.failures.isEmpty {
                let details = result.failures.prefix(5).joined(separator: "\n")
                let remainder = result.failures.count > 5
                    ? "\n…and \(result.failures.count - 5) more failure(s)."
                    : ""
                app.errorMessage = "Google Sheets sync could not complete:\n\n\(details)\(remainder)"
            }
        }
    }
}

struct MetadataView: View {
    var body: some View {
        VStack {
            ContentUnavailableView("Metadata workspace", systemImage: "doc.text.magnifyingglass", description: Text("Use Find Events to inspect existing metadata. Direct metadata editing can be added here without changing the Python data model."))
        }.frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

struct SettingsView: View {
    @EnvironmentObject private var app: AppState
    @State private var eventYear = ""
    @State private var sharedRoot = ""
    @State private var localRoot = ""
    @State private var sheetsCredentialsFile = ""
    @State private var sheetsSpreadsheetID = ""
    @State private var sheetsWorksheetName = "Events"
    @State private var choosingSheetsCredentials = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                PageHeader(title: "Settings", subtitle: "These folders and defaults are saved locally on this Mac.")
                Card {
                    VStack(alignment: .leading, spacing: 16) {
                        Label("Event locations", systemImage: "externaldrive.connected.to.line.below").font(.headline)
                        Grid(alignment: .leading, verticalSpacing: 14) {
                            GridRow { Text("Default year").foregroundStyle(.secondary); TextField("2026-27", text: $eventYear).textFieldStyle(.roundedBorder) }
                            GridRow { Text("Shared drive").foregroundStyle(.secondary); TextField("Shared-drive events root", text: $sharedRoot).textFieldStyle(.roundedBorder) }
                            GridRow { Text("Local events").foregroundStyle(.secondary); TextField("Local events root", text: $localRoot).textFieldStyle(.roundedBorder) }
                        }
                        Text("Year folders use the short form, such as 2026-27. The corresponding school year is calculated by the Python backend.").font(.caption).foregroundStyle(.secondary)
                        HStack { Spacer(); Button("Save settings") { Task { await save() } }.buttonStyle(.borderedProminent).disabled(eventYear.isEmpty || sharedRoot.isEmpty || localRoot.isEmpty || app.isWorking) }
                    }
                }
                Card {
                    VStack(alignment: .leading, spacing: 16) {
                        Label("Google Sheets", systemImage: "tablecells").font(.headline)
                        Grid(alignment: .leading, verticalSpacing: 14) {
                            GridRow {
                                Text("Service account").foregroundStyle(.secondary)
                                HStack {
                                    TextField("Service-account JSON file", text: $sheetsCredentialsFile)
                                        .textFieldStyle(.roundedBorder)
                                    Button("Choose file") { choosingSheetsCredentials = true }
                                }
                            }
                            GridRow { Text("Spreadsheet ID").foregroundStyle(.secondary); TextField("Google Sheet ID", text: $sheetsSpreadsheetID).textFieldStyle(.roundedBorder) }
                            GridRow { Text("Worksheet").foregroundStyle(.secondary); TextField("Events", text: $sheetsWorksheetName).textFieldStyle(.roundedBorder) }
                        }
                        Text("Share the spreadsheet with the service-account email. These settings stay on this Mac and the JSON file is never copied into the project.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
                if let config = app.configuration {
                    Card { VStack(alignment: .leading, spacing: 8) { Text("Active destinations").font(.headline); LabeledContent("Shared drive", value: config.eventRoot); LabeledContent("Local", value: config.localEventRoot) } }
                }
            }.padding(28).frame(maxWidth: 1000, alignment: .leading)
        }
        .onChange(of: app.configuration?.defaultEventYear) { _, _ in fillFromConfig() }
        .onAppear { fillFromConfig() }
        .fileImporter(isPresented: $choosingSheetsCredentials, allowedContentTypes: [.json]) { result in
            if case .success(let url) = result { sheetsCredentialsFile = url.path }
        }
    }

    private func fillFromConfig() {
        guard let config = app.configuration else { return }
        if eventYear.isEmpty { eventYear = config.defaultEventYear }
        if sharedRoot.isEmpty { sharedRoot = config.multimediaEventsRoot }
        if localRoot.isEmpty { localRoot = config.localEventsRoot }
        if sheetsCredentialsFile.isEmpty { sheetsCredentialsFile = config.googleSheetsCredentialsFile }
        if sheetsSpreadsheetID.isEmpty { sheetsSpreadsheetID = config.googleSheetsSpreadsheetId }
        if sheetsWorksheetName == "Events" { sheetsWorksheetName = config.googleSheetsWorksheetName }
    }

    private func save() async {
        await app.saveSettings(
            SettingsPayload(
                multimediaEventsRoot: sharedRoot,
                localEventsRoot: localRoot,
                defaultEventYear: eventYear,
                googleSheetsCredentialsFile: sheetsCredentialsFile,
                googleSheetsSpreadsheetId: sheetsSpreadsheetID,
                googleSheetsWorksheetName: sheetsWorksheetName
            )
        )
    }
}

private extension DateFormatter {
    static let eventDate: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy.MM.dd"
        return formatter
    }()
}
