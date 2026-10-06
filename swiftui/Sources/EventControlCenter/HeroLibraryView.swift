import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct HeroLibraryView: View {
    private enum Tab: String, CaseIterable {
        case organize = "To Organize"
        case lightroom = "In Lightroom"
        case library = "Library"
        case featured = "Featured"
        case removed = "Removed"
    }
    private enum FolderChoice { case source, workspace, publish }

    @EnvironmentObject private var app: AppState
    @State private var tab: Tab = .organize
    @State private var assets: [HeroAsset] = []
    @State private var selected: Set<String> = []
    @State private var query = ""
    @State private var info = ""
    @State private var uncatalogued: [String] = []
    @State private var showSettings = false
    @State private var showLightroomSetup = false
    @State private var chooseFolder = false
    @State private var folderChoice: FolderChoice = .source
    @State private var sourceRoots: [String] = []
    @State private var workspaceRoot = ""
    @State private var publishRoot = ""
    @State private var grades: Set<String> = []
    @State private var sections: Set<String> = []
    @State private var category = ""
    @State private var browseGroup = ""
    @State private var subject = ""
    @State private var setting = ""
    @State private var extraKeywords: [String] = []
    @State private var keywordDraft = ""
    @State private var keywordSuggestions: [KeywordSuggestion] = []
    @State private var confirmRemove = false
    @State private var confirmPush = false
    @State private var confirmOriginalPush = false
    @State private var confirmRename = false
    @State private var pendingPushIDs: [String] = []
    @State private var pendingOriginalIDs: [String] = []
    @State private var workspace: HeroWorkspaceResponse?
    @State private var batchSize = 5
    @State private var isStaging = false
    @State private var publishingTotal = 0
    @State private var publishingCompleted = 0
    @State private var publishingCurrent = ""

    private var isPublishing: Bool { publishingTotal > 0 }

    private let gradeOptions = ["All", "Staff", "Parents", "Foundation", "Preschool", "PreK", "Kindergarten"] + (1...12).map { "Grade \($0)" }
    private let sectionOptions = ["ELC", "PYP", "MYP", "DP"]
    private let categories = ["Learning", "Community", "Sports", "Arts", "Campus", "Events", "Portrait"]
    private let browseGroups = ["Students", "Teachers & Staff", "Campus", "Community"]

    private var visible: [HeroAsset] {
        let filtered = assets.filter { asset in
            let inTab: Bool
            switch tab {
            case .organize:
                inTab = asset.removedAt == nil && asset.matchedLibraryPath == nil &&
                    ["UNREVIEWED", "NEEDS_EDIT", "APPROVED_AS_IS"].contains(asset.editState)
            case .lightroom:
                inTab = asset.removedAt == nil && asset.matchedLibraryPath == nil &&
                    ["IN_LIGHTROOM", "READY_TO_PUBLISH"].contains(asset.editState)
            case .library:
                inTab = asset.removedAt == nil &&
                    (asset.editState == "PUBLISHED" || asset.matchedLibraryPath != nil)
            case .featured: inTab = asset.removedAt == nil && asset.featured
            case .removed: inTab = asset.removedAt != nil
            }
            let matches = query.isEmpty || [asset.assetId, asset.originalFilename,
                                             asset.masterPath.map { URL(fileURLWithPath: $0).lastPathComponent } ?? "",
                                             asset.eventName ?? "", asset.category, asset.browseGroup,
                                             asset.subject, asset.setting, asset.eventKeywords.joined(separator: " "),
                                             asset.extraKeywords.joined(separator: " ")]
                .joined(separator: " ").localizedCaseInsensitiveContains(query)
            return inTab && matches
        }
        if tab == .organize {
            return filtered.sorted { left, right in
                let leftStaged = left.needsEditPath != nil
                let rightStaged = right.needsEditPath != nil
                return leftStaged == rightStaged ? left.assetId < right.assetId : leftStaged
            }
        }
        return filtered
    }

    private var selectedAssets: [HeroAsset] { assets.filter { selected.contains($0.assetId) } }
    private var singleAsset: HeroAsset? { selectedAssets.count == 1 ? selectedAssets.first : nil }
    private var readyAssets: [HeroAsset] {
        assets.filter { $0.removedAt == nil && $0.matchedLibraryPath == nil &&
            ($0.editState == "READY_TO_PUBLISH" || $0.editState == "APPROVED_AS_IS") }
    }
    private var canPushSelectedOriginals: Bool {
        let extensions: Set<String> = ["jpg", "jpeg", "png", "tif", "tiff", "heic"]
        return !selectedAssets.isEmpty && selectedAssets.allSatisfy { asset in
            extensions.contains((asset.originalFilename as NSString).pathExtension.lowercased()) &&
            asset.removedAt == nil && asset.matchedLibraryPath == nil &&
            ["UNREVIEWED", "NEEDS_EDIT", "IN_LIGHTROOM", "APPROVED_AS_IS"].contains(asset.editState)
        }
    }

    private func toggleSelection(_ assetID: String) {
        if selected.contains(assetID) {
            selected.remove(assetID)
        } else {
            selected.insert(assetID)
        }
    }

    private func displayFilename(_ asset: HeroAsset) -> String {
        guard asset.editState == "PUBLISHED", let masterPath = asset.masterPath else {
            return asset.originalFilename
        }
        return URL(fileURLWithPath: masterPath).lastPathComponent
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 18) {
                HStack(alignment: .center) {
                    VStack(alignment: .leading, spacing: 5) {
                        Text("Hero Library").font(.system(size: 28, weight: .bold, design: .rounded))
                        Text("Choose photos. Edit when needed. Publish to your shared library.")
                            .font(.subheadline).foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button("Lightroom setup", systemImage: "questionmark.circle") { showLightroomSetup = true }
                    Button("Locations", systemImage: "folder.badge.gearshape") { showSettings = true }
                }
                Picker("Library view", selection: $tab) {
                    ForEach(Tab.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                }.pickerStyle(.segmented).labelsHidden()
                workflowToolbar
            }
            .padding(24)
            Divider()
            HStack(spacing: 0) {
                VStack(alignment: .leading, spacing: 12) {
                    HStack {
                        Text("\(visible.count) photos").font(.subheadline.weight(.semibold))
                        Spacer()
                        Button(selected.isEmpty ? "Select all" : "Clear selection") {
                            selected = selected.isEmpty ? Set(visible.map(\.assetId)) : []
                        }.buttonStyle(.link).disabled(visible.isEmpty || isPublishing)
                        TextField("Search photos", text: $query)
                            .textFieldStyle(.roundedBorder).frame(maxWidth: 230)
                    }
                    if !info.isEmpty {
                        Text(info).font(.caption).foregroundStyle(.secondary)
                            .lineLimit(2).help(info)
                    }
                    ScrollView {
                        VStack(alignment: .leading, spacing: 16) {
                            if !uncatalogued.isEmpty { staffAdditionsCard }
                            if visible.isEmpty {
                                ContentUnavailableView(
                                    query.isEmpty ? "No photos in this view" : "No matching photos",
                                    systemImage: "photo.stack",
                                    description: Text(emptyMessage)
                                ).frame(maxWidth: .infinity, minHeight: 250)
                            } else {
                                assetList
                            }
                        }
                    }
                }
                .padding(20)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                Divider()
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        if let asset = singleAsset { detail(asset) }
                        if selected.isEmpty {
                            VStack(alignment: .leading, spacing: 10) {
                                Label("Photo details", systemImage: "sidebar.right").font(.headline)
                                Text("Select a photo to preview it and edit its metadata. Select several to apply changes together.")
                                    .font(.subheadline).foregroundStyle(.secondary)
                            }.padding(20)
                        } else {
                            actionsCard
                        }
                    }
                    .padding(16)
                }
                .frame(width: 330)
                .background(Color(nsColor: .controlBackgroundColor).opacity(0.35))
            }
        }
        .sheet(isPresented: $showLightroomSetup) { lightroomSetupSheet }
        .sheet(isPresented: $showSettings) {
            VStack(alignment: .leading, spacing: 18) {
                HStack {
                    Text("Hero Library locations").font(.title2.bold())
                    Spacer()
                    Button("Done") { showSettings = false }.keyboardShortcut(.cancelAction)
                }
                settingsCard
            }.padding(24).frame(width: 650)
            .fileImporter(isPresented: $chooseFolder, allowedContentTypes: [.folder]) { result in
                if case .success(let url) = result {
                    switch folderChoice {
                    case .source: if !sourceRoots.contains(url.path) { sourceRoots.append(url.path) }
                    case .workspace: workspaceRoot = url.path
                    case .publish: publishRoot = url.path
                    }
                }
            }
        }
        .task {
            fillSettings()
            workspace = await app.heroWorkspace()
            await scanTags()
        }
        .task { keywordSuggestions = await app.keywordVocabulary() }
        .onChange(of: tab) { _, _ in selected = [] }
        .confirmationDialog("Remove selected photos from the Hero Library?", isPresented: $confirmRemove) {
            Button("Remove from Library", role: .destructive) { Task { await removeSelected() } }
            Button("Cancel", role: .cancel) { }
        } message: {
            Text("ECC moves its managed copies to _Removed. The original event photos stay in the archive, and you can restore these later.")
        }
        .confirmationDialog("Push finished photos to the shared Hero Shot Library?", isPresented: $confirmPush) {
            Button("Push \(pendingPushIDs.count) photos") { Task { await push(pendingPushIDs) } }
            Button("Cancel", role: .cancel) { }
        } message: {
            Text("ECC moves full-quality Lightroom exports into subject MASTER folders on Drive, creates WEB versions, then clears each successful photo from local Needs Edit. Original archive files stay in place.")
        }
        .confirmationDialog("Publish selected originals without editing?", isPresented: $confirmOriginalPush) {
            Button("Publish \(pendingOriginalIDs.count) originals") { Task { await pushOriginals(pendingOriginalIDs) } }
            Button("Cancel", role: .cancel) { }
        } message: {
            Text("ECC reads only these selected photos, copies them to MASTER in the Hero Shot Library, and makes WEB versions. The source archive files stay in place.")
        }
        .confirmationDialog("Update published Hero filenames?", isPresented: $confirmRename) {
            Button("Rename MASTER and WEB files") { Task { await renamePublished() } }
            Button("Cancel", role: .cancel) { }
        } message: {
            Text("ECC names files with their event, date, and event photo number, then updates its catalog. Links that use the old filenames may need updating.")
        }
        .overlay(alignment: .bottom) {
            if isPublishing {
                HStack(spacing: 12) {
                    ProgressView().controlSize(.small)
                    VStack(alignment: .leading, spacing: 5) {
                        Text("Publishing to Drive · \(publishingCompleted) of \(publishingTotal) processed")
                            .font(.subheadline.weight(.semibold))
                        Text(publishingCurrent).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                        ProgressView(value: Double(publishingCompleted), total: Double(publishingTotal))
                    }
                }
                .padding(14)
                .frame(maxWidth: 360)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14))
                .shadow(radius: 8)
                .padding(18)
            }
        }
    }

    private var assetList: some View {
        LazyVStack(spacing: 0) {
            ForEach(visible) { asset in
                HStack(spacing: 12) {
                    // Keep the small checkbox familiar, but give it a full row-height
                    // button target. This avoids the first visible row receiving only
                    // part of a click after the selected-photo panel appears above it.
                    Button { toggleSelection(asset.assetId) } label: {
                        Image(systemName: selected.contains(asset.assetId) ? "checkmark.square.fill" : "square")
                            .font(.system(size: 17, weight: .medium))
                            .foregroundStyle(selected.contains(asset.assetId) ? Color.accentColor : .secondary)
                            .frame(width: 36, height: 88)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(selected.contains(asset.assetId) ? "Deselect \(displayFilename(asset))" : "Select \(displayFilename(asset))")
                    .accessibilityValue(selected.contains(asset.assetId) ? "Selected" : "Not selected")
                    HeroAssetPreview(asset: asset, size: 88)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(displayFilename(asset))
                            .font(.subheadline.weight(.semibold)).lineLimit(1)
                        Text("\(asset.assetId) · \(asset.eventName?.isEmpty == false ? asset.eventName! : "General School Life")")
                            .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                        Text(asset.eventKeywords.joined(separator: ", ")).font(.caption2).foregroundStyle(.tertiary).lineLimit(1)
                    }
                    Spacer()
                    if asset.featured { Image(systemName: "star.fill").foregroundStyle(.yellow) }
                    Text(asset.editState == "PUBLISHED" ? "On Drive" :
                         asset.matchedLibraryPath != nil ? "Already on Drive" :
                         asset.editState == "READY_TO_PUBLISH" ? "Export ready" :
                         asset.editState == "IN_LIGHTROOM" ? "In Lightroom" :
                         asset.editState == "APPROVED_AS_IS" ? "Original ready" :
                         asset.needsEditPath == nil ? "Awaiting stage" : "To organize")
                        .font(.caption2).padding(6).background(.cyan.opacity(0.14), in: Capsule())
                }
                .padding(.horizontal, 12).padding(.vertical, 9)
                .contentShape(Rectangle())
                Divider()
            }
        }
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
    }

    private func detail(_ asset: HeroAsset) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HeroAssetPreview(asset: asset, size: 240)
                .frame(maxWidth: .infinity)
            Text(asset.assetId).font(.headline)
            Text(displayFilename(asset)).font(.subheadline).lineLimit(2)
            if let date = asset.eventDate, !date.isEmpty { Text(date).font(.caption) }
            if let year = asset.schoolYear, !year.isEmpty { Text("School year: \(year)").font(.caption) }
            if !asset.eventGrades.isEmpty { Text("Event grades: \(asset.eventGrades.joined(separator: ", "))").font(.caption) }
            if !asset.eventSections.isEmpty { Text("Event sections: \(asset.eventSections.joined(separator: ", "))").font(.caption) }
            if !asset.eventKeywords.isEmpty { Text("Event keywords: \(asset.eventKeywords.joined(separator: ", "))").font(.caption) }
            if !asset.eventDescription.isEmpty { Text(asset.eventDescription).font(.caption) }
            if !asset.grades.isEmpty { Text("Photo grades: \(asset.grades.joined(separator: ", "))").font(.caption) }
            if !asset.browseGroup.isEmpty { Text("Browse folder: \(asset.browseGroup)").font(.caption) }
            DisclosureGroup("File locations") {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Source: \(asset.sourcePath)")
                    if let master = asset.masterPath { Text("MASTER: \(master)") }
                    if let matched = asset.matchedLibraryPath { Text("Drive match: \(matched)") }
                }.font(.caption2).foregroundStyle(.secondary).textSelection(.enabled)
            }
        }
        .padding(0)
    }

    private var actionsCard: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("\(selected.count) selected").font(.headline)
            if tab == .removed {
                Button("Restore to Library", systemImage: "arrow.uturn.backward") { Task { await restoreSelected() } }
                    .buttonStyle(.borderedProminent)
            } else {
                if tab == .organize {
                    Button("Send selected to Lightroom", systemImage: "arrow.right") { Task { await stage(Array(selected)) } }
                        .disabled(selectedAssets.contains { $0.needsEditPath == nil })
                        .help("Stage photos locally before sending them to Lightroom.")
                    Button("Publish originals", systemImage: "icloud.and.arrow.up") {
                        pendingOriginalIDs = selectedAssets.map(\.assetId)
                        confirmOriginalPush = true
                    }.buttonStyle(.borderedProminent).disabled(!canPushSelectedOriginals)
                    Text("Publish finished JPEG, PNG, TIFF, or HEIC photos directly when no editing is needed.")
                        .font(.caption).foregroundStyle(.secondary)
                    Menu("Review status") {
                        Button("Needs edit") { Task { await setState("NEEDS_EDIT") } }
                        Button("Original ready") { Task { await setState("APPROVED_AS_IS") } }
                    }.fixedSize()
                }
                if tab == .lightroom {
                    Button("Publish selected exports", systemImage: "icloud.and.arrow.up") { confirmSelectedPush() }
                        .buttonStyle(.borderedProminent)
                        .disabled(selectedAssets.contains { $0.editState != "READY_TO_PUBLISH" })
                }
                Divider()
                DisclosureGroup("Edit metadata") {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            Menu(grades.isEmpty ? "Grades" : "Grades (\(grades.count))") {
                                ForEach(gradeOptions, id: \.self) { grade in
                                    Toggle(grade, isOn: Binding(get: { grades.contains(grade) }, set: { if $0 { grades.insert(grade) } else { grades.remove(grade) } }))
                                }
                            }
                            Menu(sections.isEmpty ? "Sections" : "Sections (\(sections.count))") {
                                ForEach(sectionOptions, id: \.self) { section in
                                    Toggle(section, isOn: Binding(get: { sections.contains(section) }, set: { if $0 { sections.insert(section) } else { sections.remove(section) } }))
                                }
                            }
                        }
                        Picker("Category", selection: $category) {
                            Text("No change").tag("")
                            ForEach(categories, id: \.self) { Text($0).tag($0) }
                        }
                        Picker("Library folder", selection: $browseGroup) {
                            Text("Auto").tag("")
                            ForEach(browseGroups, id: \.self) { Text($0).tag($0) }
                        }
                        TextField("Subject or activity", text: $subject)
                        TextField("Setting", text: $setting)
                        TagEditor(tags: $extraKeywords, draft: $keywordDraft, suggestions: keywordSuggestions)
                        Text("Only filled fields are applied to the selected photos.")
                            .font(.caption).foregroundStyle(.secondary)
                        Button("Apply metadata & organize") { Task { await applyMetadata() } }
                    }.textFieldStyle(.roundedBorder).padding(.top, 10)
                }
                HStack {
                    Button("Feature", systemImage: "star") { Task { await update(["featured": .flag(true)]) } }
                    Button("Unfeature") { Task { await update(["featured": .flag(false)]) } }
                }
                Divider()
                Button("Remove from Library", systemImage: "trash", role: .destructive) { confirmRemove = true }
            }
        }
        .disabled(app.isWorking || isPublishing || isStaging)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var queuedIDs: [String] {
        assets.filter { $0.removedAt == nil && $0.matchedLibraryPath == nil && $0.editState == "NEEDS_EDIT" && $0.needsEditPath != nil }.map(\.assetId)
    }

    private var emptyMessage: String {
        if !query.isEmpty { return "Try another search or clear the search field." }
        switch tab {
        case .organize: return "Scan Finder’s Hero Shot tags, then stage a small batch to review."
        case .lightroom: return "Send queued photos to Lightroom. Check exports when your edits are finished."
        case .library: return "Your published photos and existing Drive matches appear here."
        case .featured: return "Feature selected photos to keep your best images together."
        case .removed: return "Removed photos appear here and can be restored."
        }
    }

    private var workflowToolbar: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 12) { workflowActions; Spacer(minLength: 8); moreMenu }
            VStack(alignment: .leading, spacing: 10) {
                workflowActions
                moreMenu
            }
        }
        .controlSize(.large)
        .disabled(app.isWorking || isPublishing || isStaging)
    }

    @ViewBuilder private var workflowActions: some View {
        switch tab {
        case .organize:
            HStack(spacing: 10) {
                Button("Scan tags", systemImage: "arrow.clockwise") { Task { await scanTags() } }
                Button(isStaging ? "Staging…" : "Stage next batch", systemImage: "square.and.arrow.down") { Task { await stageNextBatch() } }
                    .buttonStyle(.borderedProminent)
                Picker("Batch size", selection: $batchSize) {
                    Text("3 photos").tag(3); Text("5 photos").tag(5); Text("10 photos").tag(10)
                }.labelsHidden().frame(width: 100)
                Button("Send queued (\(queuedIDs.count))", systemImage: "arrow.right") { Task { await stage(queuedIDs) } }
                    .disabled(queuedIDs.isEmpty)
            }
        case .lightroom:
            HStack(spacing: 10) {
                Button("Check exports", systemImage: "arrow.clockwise") { Task { await matchExports() } }
                Button("Publish ready (\(readyAssets.filter { $0.editState == "READY_TO_PUBLISH" }.count))", systemImage: "icloud.and.arrow.up") {
                    pendingPushIDs = readyAssets.filter { $0.editState == "READY_TO_PUBLISH" }.map(\.assetId)
                    confirmPush = true
                }.buttonStyle(.borderedProminent)
                    .disabled(!readyAssets.contains { $0.editState == "READY_TO_PUBLISH" })
                Button("Open Lightroom", systemImage: "camera.aperture") { Task { await openCatalog() } }
            }
        case .library:
            Button("Review staff additions", systemImage: "person.crop.rectangle.stack") { Task { await auditDrive() } }
        case .featured:
            Label("Your selected highlights", systemImage: "star").foregroundStyle(.secondary)
        case .removed:
            Label("Select photos to restore them", systemImage: "arrow.uturn.backward").foregroundStyle(.secondary)
        }
    }

    private var moreMenu: some View {
        Menu {
            if tab != .organize {
                Button("Scan Hero Shot tags", systemImage: "arrow.clockwise") { Task { await scanTags() } }
                Divider()
            }
            Button("Open Lightroom Catalog", systemImage: "camera.aperture") { Task { await openCatalog() } }
            Button("Open editing workspace", systemImage: "folder") { Task { await openNeedsEdit() } }
            Button("Open shared library", systemImage: "externaldrive") { NSWorkspace.shared.open(URL(fileURLWithPath: publishRoot)) }
                .disabled(publishRoot.isEmpty)
            if tab == .library {
                Divider()
                Button("Refresh Drive folders", systemImage: "square.grid.2x2") { Task { await reorganizeDrive() } }
                Button("Update existing filenames", systemImage: "textformat") { confirmRename = true }
            }
        } label: { Label("More", systemImage: "ellipsis.circle") }
        .fixedSize()
    }

    private var staffAdditionsCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Staff additions · \(uncatalogued.count)").font(.headline)
            Text("Review photos added directly to Drive before adding them to ECC.")
                .font(.caption).foregroundStyle(.secondary)
            ForEach(uncatalogued, id: \.self) { path in
                HStack {
                    Text((path as NSString).lastPathComponent).lineLimit(1).help(path)
                    Spacer()
                    Button("Show") { NSWorkspace.shared.selectFile((publishRoot as NSString).appendingPathComponent(path), inFileViewerRootedAtPath: "") }
                    Button("Add to ECC") { Task { await adoptDrive(path) } }.disabled(app.isWorking)
                }.font(.caption)
            }
        }.padding(16).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
    }

    private var lightroomSetupSheet: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack {
                VStack(alignment: .leading, spacing: 5) {
                    Text("Lightroom Classic setup").font(.title2.bold())
                    Text("Set up Auto Import once, then edit each batch in Lightroom.")
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button("Done") { showLightroomSetup = false }.keyboardShortcut(.cancelAction)
            }
            if let workspace {
                setupStep("1", title: "Open the Hero Library catalog", description: "Use ECC’s dedicated catalog for your Hero photos.")
                Button("Open Lightroom Catalog", systemImage: "camera.aperture") { Task { await openCatalog() } }
                Divider()
                setupStep("2", title: "Configure Auto Import in Lightroom", description: "Choose File → Auto Import → Auto Import Settings. Set Watched Folder to the empty Incoming folder and Move To to Working Lightroom Edits. Keep original filenames, then enable Auto Import.")
                setupFolder("Watched folder", path: workspace.incomingPath)
                setupFolder("Move to", path: workspace.workingPath)
                Divider()
                setupStep("3", title: "Send a batch, edit, and export", description: "Stage photos in ECC and choose Send queued. Export finished, full-quality photos to Exports, keeping the ECC Asset ID at the start of each filename. Back in In Lightroom, choose Check exports, then Publish ready. ECC creates the smaller WEB copies for you.")
                setupFolder("Export folder", path: workspace.exportPath)
            } else {
                ProgressView("Loading editing workspace…")
            }
        }
        .padding(28).frame(width: 640)
    }

    private func setupStep(_ number: String, title: String, description: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Text(number).font(.headline).frame(width: 28, height: 28)
                .background(.cyan.opacity(0.16), in: Circle())
            VStack(alignment: .leading, spacing: 5) {
                Text(title).font(.headline)
                Text(description).font(.subheadline).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func setupFolder(_ label: String, path: String) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack {
                Text(label).font(.subheadline.weight(.medium))
                Spacer()
                Button("Open folder", systemImage: "folder") { NSWorkspace.shared.open(URL(fileURLWithPath: path)) }
            }
            Text(path).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
        }.padding(12).background(.quaternary, in: RoundedRectangle(cornerRadius: 10))
    }

    private var settingsCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Scan Hero Shot tags reads Finder metadata. Stage next batch copies a small group into local Needs Edit. Google Drive receives files only when you push finished photos.")
                .font(.caption).foregroundStyle(.secondary)
            ForEach(sourceRoots, id: \.self) { root in
                HStack { Text(root).font(.caption).textSelection(.enabled); Spacer(); Button("Remove") { sourceRoots.removeAll { $0 == root } } }
            }
            Button("Add source folder") { folderChoice = .source; chooseFolder = true }
            HStack {
                TextField("Local Hero editing workspace", text: $workspaceRoot)
                Button("Choose") { folderChoice = .workspace; chooseFolder = true }
            }
            HStack {
                TextField("Shared-drive Hero Shot Library folder", text: $publishRoot)
                Button("Choose") { folderChoice = .publish; chooseFolder = true }
            }
            Button("Save locations") { Task { await saveSettings() } }.buttonStyle(.borderedProminent)
        }
        .textFieldStyle(.roundedBorder)
        .padding(18).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
    }

    private func fillSettings() {
        guard let config = app.configuration else { return }
        sourceRoots = config.heroSourceRoots
        workspaceRoot = config.heroWorkspaceRoot
        publishRoot = config.heroPublishRoot
    }

    private func scanTags() async {
        info = "Checking Finder tags and event metadata without downloading photos…"
        if let result = await app.heroScan() {
            assets = result.assets
            let staged = result.assets.filter { $0.needsEditPath != nil && $0.editState != "PUBLISHED" }.count
            let onDrive = result.assets.filter { $0.matchedLibraryPath != nil || $0.editState == "PUBLISHED" }.count
            info = "Found \(result.found) tagged photos; \(staged) staged locally, \(onDrive) already on Drive. Choose Stage next batch to copy up to \(batchSize) more." +
                (result.errors.isEmpty ? "" : " \(result.errors.joined(separator: "; "))")
        }
    }
    private func stageNextBatch() async {
        guard !isStaging else { return }
        isStaging = true
        defer { isStaging = false }
        var staged = 0
        for _ in 0..<batchSize {
            if Task.isCancelled { break }
            guard let result = await app.heroRefresh(limit: 1) else { break }
            assets = result.assets
            staged += result.synced
            info = "Staged \(staged) of \(batchSize) in this batch · \(result.pending) still waiting locally." +
                (result.errors.isEmpty ? "" : " \(result.errors.joined(separator: "; "))")
            if result.synced == 0 || result.pending == 0 { break }
        }
    }
    private func openCatalog() async {
        guard let paths = await app.heroWorkspace() else { return }
        workspace = paths
        NSWorkspace.shared.open(URL(fileURLWithPath: paths.catalogPath))
        info = "Opened the Hero Library catalog in Lightroom Classic."
    }
    private func openNeedsEdit() async {
        guard let paths = await app.heroWorkspace() else { return }
        workspace = paths
        NSWorkspace.shared.open(URL(fileURLWithPath: paths.incomingPath).deletingLastPathComponent())
    }
    private func matchExports() async {
        if let result = await app.heroMatchExports() {
            assets = result.assets
            info = "Matched \(result.matched) Lightroom exports."
        }
    }
    private func preparePush() async {
        if let result = await app.heroMatchExports() {
            assets = result.assets
            pendingPushIDs = result.assets.filter { $0.removedAt == nil && $0.matchedLibraryPath == nil &&
                ($0.editState == "READY_TO_PUBLISH" || $0.editState == "APPROVED_AS_IS") }.map(\.assetId)
            if pendingPushIDs.isEmpty {
                info = "No finished Lightroom exports found. Export full-quality files to Needs Edit/Exports with the Asset ID at the start of each filename."
            } else {
                confirmPush = true
            }
        }
    }
    private func confirmSelectedPush() {
        pendingPushIDs = selectedAssets.map(\.assetId)
        confirmPush = true
    }
    private func update(_ changes: [String: HeroValue]) async {
        if let result = await app.heroUpdate(ids: Array(selected), changes: changes) {
            assets = result.assets
            guard !changes.isEmpty else { return }
            var message = "Saved metadata"
            if result.metadataEmbedded > 0 {
                message += " and embedded it in \(result.metadataEmbedded) photo file\(result.metadataEmbedded == 1 ? "" : "s")"
            }
            if result.organized > 0 {
                message += ". Organized \(result.organized) Drive photo\(result.organized == 1 ? "" : "s")"
            }
            if !result.errors.isEmpty {
                message += ". \(result.errors.joined(separator: "; "))"
            }
            info = message + "."
        }
    }
    private func setState(_ state: String) async { await update(["edit_state": .text(state)]) }
    private func stage(_ ids: [String]) async {
        guard !ids.isEmpty else { return }
        if let result = await app.heroStage(ids: ids) {
            assets = result
            info = "Sent \(ids.count) local photos to Lightroom Incoming. Lightroom Classic will move them to Working Lightroom Edits when Auto Import is enabled."
        }
    }
    private func push(_ ids: [String]) async {
        await publish(ids, originals: false)
    }
    private func pushOriginals(_ ids: [String]) async {
        await publish(ids, originals: true)
    }
    private func publish(_ ids: [String], originals: Bool) async {
        guard !ids.isEmpty && !isPublishing else { return }
        publishingTotal = ids.count
        publishingCompleted = 0
        defer {
            publishingTotal = 0
            publishingCompleted = 0
            publishingCurrent = ""
        }

        var published: [String] = []
        var errors: [String] = []
        for (index, id) in ids.enumerated() {
            publishingCurrent = assets.first { $0.assetId == id }?.originalFilename ?? id
            let result = originals ? await app.heroPushOriginals(ids: [id]) : await app.heroPushBatch(ids: [id])
            guard let result else {
                errors.append("Publishing stopped while processing \(id).")
                break
            }
            assets = result.assets
            if result.pushed == 1 {
                published.append(id)
                selected.remove(id)
            }
            errors.append(contentsOf: result.errors)
            publishingCompleted = index + 1
        }

        if errors.isEmpty && published.count == ids.count {
            selected = []
            query = ""
            tab = .library
            info = "Published \(published.count) \(originals ? "original" : "finished") photo(s) to the Hero Library. Google Drive may continue syncing in the background."
        } else {
            info = "Published \(published.count) of \(ids.count) photo(s). Successful photos moved to Library; remaining photos can be retried from their workflow tab." +
                (errors.isEmpty ? "" : " Issues: \(errors.joined(separator: "; "))")
        }
    }
    private func reorganizeDrive() async {
        if let result = await app.heroReorganize() {
            assets = result.assets
            info = "Moved \(result.moved) published photos into MASTER and WEB subject folders." +
                (result.errors.isEmpty ? "" : " Issues: \(result.errors.joined(separator: "; "))")
        }
    }
    private func renamePublished() async {
        info = "Updating published Hero filenames…"
        if let result = await app.heroRenamePublished() {
            assets = result.assets
            info = "Updated \(result.renamed) published photo filename(s)." +
                (result.errors.isEmpty ? "" : " Issues: \(result.errors.joined(separator: "; "))")
        }
    }
    private func auditDrive() async {
        if let result = await app.heroAuditDrive() {
            uncatalogued = result.uncatalogued
            info = result.count == 0 ? "Every Drive photo is represented in the Hero catalog." :
                "Found \(result.count) photos added directly to Drive. Review them below; ECC has not moved or downloaded them."
        }
    }
    private func adoptDrive(_ path: String) async {
        if let result = await app.heroAdoptDrive(path: path) {
            assets = result.assets
            uncatalogued.removeAll { $0 == path }
            tab = .organize
            selected = []
            query = result.added.first ?? ""
            info = "Added \(path) to the Hero inbox. Select it to add metadata, send it to Lightroom, or publish the original if it needs no edit. Clear Search to see the full inbox."
        }
    }
    private func removeSelected() async {
        if let result = await app.heroRemove(ids: Array(selected)) {
            assets = result
            selected = []
            info = "Removed from the library. Original event photos remain in the archive."
        }
    }
    private func restoreSelected() async {
        if let result = await app.heroRestore(ids: Array(selected)) {
            assets = result
            selected = []
            info = "Restored to the library."
        }
    }
    private func applyMetadata() async {
        var changes: [String: HeroValue] = [:]
        if !grades.isEmpty { changes["grades"] = .texts(Array(grades)) }
        if !sections.isEmpty { changes["sections"] = .texts(Array(sections)) }
        if !category.isEmpty { changes["category"] = .text(category) }
        if !browseGroup.isEmpty { changes["browse_group"] = .text(browseGroup) }
        if !subject.isEmpty { changes["subject"] = .text(subject) }
        if !setting.isEmpty { changes["setting"] = .text(setting) }
        let finalKeywords = KeywordTags.canonicalized(extraKeywords + [keywordDraft], using: keywordSuggestions)
        if !finalKeywords.isEmpty { changes["extra_keywords"] = .texts(finalKeywords) }
        if !changes.isEmpty { await update(changes) }
    }
    private func saveSettings() async {
        await app.heroSaveSettings(HeroSettingsPayload(sourceRoots: sourceRoots, workspaceRoot: workspaceRoot, publishRoot: publishRoot))
        fillSettings()
        workspace = await app.heroWorkspace()
        showSettings = false
        await scanTags()
    }
}
