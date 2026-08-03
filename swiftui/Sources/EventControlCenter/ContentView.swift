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
            .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(.white.opacity(0.08)))
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
    @State private var sessionGap = 20
    @State private var scan: MediaScan?
    @State private var selectedSessions: Set<Int> = []
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
            if case .success(let url) = result { sourcePath = url.path; scan = nil }
        }
        .onChange(of: app.configuration?.defaultSchoolYear) { _, year in
            if schoolYear.isEmpty { schoolYear = year ?? "" }
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
                TextEditor(text: $description).font(.body).frame(height: 84).scrollContentBackground(.hidden)
                    .padding(8).background(.black.opacity(0.22), in: RoundedRectangle(cornerRadius: 10))
                    .overlay(alignment: .topLeading) { if description.isEmpty { Text("Description").foregroundStyle(.tertiary).padding(14).allowsHitTesting(false) } }
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
                HStack {
                    Text(sourcePath.isEmpty ? "Choose an SD card or media folder." : sourcePath).lineLimit(1).foregroundStyle(sourcePath.isEmpty ? .secondary : .primary)
                    Spacer()
                    Button("Choose folder") { choosingSource = true }
                }
                HStack {
                    Stepper("Session gap: \(sessionGap) minutes", value: $sessionGap, in: 1...120).frame(maxWidth: 260)
                    Spacer()
                    Button { Task { await scanMedia() } } label: { Label("Scan media", systemImage: "viewfinder") }
                        .buttonStyle(.bordered).disabled(sourcePath.isEmpty || app.isWorking)
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
                HStack {
                    Button("Select all") { selectedSessions = Set(scan.sessions.map(\.index)) }.buttonStyle(.link)
                    Button("Select none") { selectedSessions = [] }.buttonStyle(.link)
                    Spacer()
                    Button { Task { await importSelected() } } label: { Label("Import selected media", systemImage: "square.and.arrow.down.fill") }
                        .buttonStyle(.borderedProminent).disabled(currentFolder == nil || selectedSessions.isEmpty || app.isWorking)
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
        if let value = await app.scan(source: sourcePath, gap: sessionGap) {
            scan = value; selectedSessions = Set(value.sessions.map(\.index))
        }
    }

    private func importSelected() async {
        guard let currentFolder else { return }
        let payload = ImportMediaPayload(source: sourcePath, eventFolder: currentFolder, sessionGapMinutes: sessionGap, sessionIndexes: selectedSessions.sorted(), eventName: eventName)
        if let outcome = await app.importMedia(payload) {
            app.notice = "Imported \(outcome.photosImported) photos and \(outcome.videosImported) videos. Generated \(outcome.jpgsGenerated) JPGs."
        }
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
            VStack(alignment: .leading, spacing: 3) {
                Text("Session \(session.index)").fontWeight(.semibold)
                Text("\(time(session.startTime))–\(time(session.endTime)) · \(session.photoCount) photos · \(session.videoCount) videos")
                    .font(.caption).foregroundStyle(.secondary)
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
                Card { Label("Google Sheets synchronization and archiving remain available through the Python services. They can be added here with the same bridge pattern when their workflow is finalized.", systemImage: "info.circle").font(.subheadline).foregroundStyle(.secondary) }
            }.padding(28).frame(maxWidth: 1050, alignment: .leading)
        }
        .fileImporter(isPresented: $selectingFolder, allowedContentTypes: [.folder]) { if case .success(let url) = $0 { eventFolder = url.path } }
        .fileImporter(isPresented: $choosingYearRoot, allowedContentTypes: [.folder]) { if case .success(let url) = $0 { yearRoot = url.path } }
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
                if let config = app.configuration {
                    Card { VStack(alignment: .leading, spacing: 8) { Text("Active destinations").font(.headline); LabeledContent("Shared drive", value: config.eventRoot); LabeledContent("Local", value: config.localEventRoot) } }
                }
            }.padding(28).frame(maxWidth: 1000, alignment: .leading)
        }
        .onChange(of: app.configuration?.defaultEventYear) { _, _ in fillFromConfig() }
        .onAppear { fillFromConfig() }
    }

    private func fillFromConfig() {
        guard let config = app.configuration else { return }
        if eventYear.isEmpty { eventYear = config.defaultEventYear }
        if sharedRoot.isEmpty { sharedRoot = config.multimediaEventsRoot }
        if localRoot.isEmpty { localRoot = config.localEventsRoot }
    }

    private func save() async {
        await app.saveSettings(SettingsPayload(multimediaEventsRoot: sharedRoot, localEventsRoot: localRoot, defaultEventYear: eventYear))
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
