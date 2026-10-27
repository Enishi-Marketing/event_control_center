import SwiftUI

enum KeywordTags {
    static func cleaned(_ value: String) -> String {
        value.split(whereSeparator: \.isWhitespace).joined(separator: " ")
    }

    static func key(_ value: String) -> String {
        cleaned(value).folding(options: .caseInsensitive, locale: nil)
    }

    static func canonicalized(_ values: [String], using vocabulary: [KeywordSuggestion]) -> [String] {
        let known = Dictionary(uniqueKeysWithValues: vocabulary.map { ($0.normalizedValue, $0.displayValue) })
        var unique: [String: String] = [:]
        for value in values {
            for part in value.split(separator: ",", omittingEmptySubsequences: false) {
                let display = cleaned(String(part))
                let normalized = key(display)
                if !normalized.isEmpty && unique[normalized] == nil {
                    unique[normalized] = known[normalized] ?? display
                }
            }
        }
        return unique.values.sorted { $0.localizedCaseInsensitiveCompare($1) == .orderedAscending }
    }

    static func matches(_ query: String, in vocabulary: [KeywordSuggestion], excluding tags: [String]) -> [KeywordSuggestion] {
        let needle = key(query)
        guard !needle.isEmpty else { return [] }
        let excluded = Set(tags.map(key))
        var matches = vocabulary.filter { $0.normalizedValue.contains(needle) && !excluded.contains($0.normalizedValue) }
        func rank(_ value: String) -> Int {
            if value.hasPrefix(needle) { return 0 }
            if value.split(separator: " ").dropFirst().contains(where: { $0.hasPrefix(needle) }) { return 1 }
            return 2
        }
        matches.sort {
            let left = rank($0.normalizedValue), right = rank($1.normalizedValue)
            if left != right { return left < right }
            if $0.usageCount != $1.usageCount { return $0.usageCount > $1.usageCount }
            if $0.lastUsed != $1.lastUsed { return $0.lastUsed > $1.lastUsed }
            return $0.displayValue.localizedCaseInsensitiveCompare($1.displayValue) == .orderedAscending
        }
        return Array(matches.prefix(8))
    }

    static func bank(in vocabulary: [KeywordSuggestion], excluding tags: [String]) -> [KeywordSuggestion] {
        let excluded = Set(tags.map(key))
        return vocabulary.filter { !excluded.contains($0.normalizedValue) }.sorted {
            if $0.usageCount != $1.usageCount { return $0.usageCount > $1.usageCount }
            if $0.lastUsed != $1.lastUsed { return $0.lastUsed > $1.lastUsed }
            return $0.displayValue.localizedCaseInsensitiveCompare($1.displayValue) == .orderedAscending
        }
    }
}

struct TagEditor: View {
    @Binding var tags: [String]
    @Binding var draft: String
    let suggestions: [KeywordSuggestion]

    @FocusState private var inputFocused: Bool
    @State private var showSuggestions = true
    @State private var highlighted = -1
    @State private var showAllKeywords = false

    private var bank: [KeywordSuggestion] {
        KeywordTags.bank(in: suggestions, excluding: tags)
    }

    private var visibleBank: [KeywordSuggestion] {
        showAllKeywords ? bank : Array(bank.prefix(12))
    }

    private var matches: [KeywordSuggestion] {
        KeywordTags.matches(draft, in: suggestions, excluding: tags)
    }

    private var hasQuery: Bool { !KeywordTags.cleaned(draft).isEmpty }
    private var canAddNew: Bool {
        !suggestions.contains { $0.normalizedValue == KeywordTags.key(draft) }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Keywords").font(.subheadline.weight(.medium))
            HStack(spacing: 6) {
                ForEach(tags, id: \.self) { tag in
                    Button {
                        tags.removeAll { KeywordTags.key($0) == KeywordTags.key(tag) }
                    } label: {
                        Label(tag, systemImage: "xmark")
                            .font(.caption)
                            .padding(.horizontal, 9)
                            .padding(.vertical, 5)
                            .background(.cyan.opacity(0.18), in: Capsule())
                    }
                    .buttonStyle(.plain)
                    .help("Remove keyword \(tag)")
                    .accessibilityLabel("Remove keyword \(tag)")
                }
                TextField("Add keyword", text: $draft)
                    .textFieldStyle(.roundedBorder)
                    .focused($inputFocused)
                    .onSubmit(commitHighlightedOrDraft)
                    .onKeyPress(.downArrow) {
                        guard hasQuery && !matches.isEmpty else { return .ignored }
                        showSuggestions = true
                        highlighted = min(highlighted + 1, matches.count - 1)
                        return .handled
                    }
                    .onKeyPress(.upArrow) {
                        guard hasQuery && !matches.isEmpty else { return .ignored }
                        showSuggestions = true
                        highlighted = max(highlighted - 1, 0)
                        return .handled
                    }
                    .onKeyPress(.escape) {
                        showSuggestions = false
                        highlighted = -1
                        return .handled
                    }
                    .onKeyPress(.delete) {
                        guard draft.isEmpty, !tags.isEmpty else { return .ignored }
                        tags.removeLast()
                        return .handled
                    }
            }
            if inputFocused && showSuggestions && hasQuery && (!matches.isEmpty || canAddNew) {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(matches.indices, id: \.self) { index in
                        Button {
                            add(matches[index].displayValue)
                        } label: {
                            Text(matches[index].displayValue)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(.horizontal, 10).padding(.vertical, 7)
                                .background(index == highlighted ? Color.cyan.opacity(0.18) : .clear)
                        }
                        .buttonStyle(.plain)
                    }
                    if canAddNew {
                        Button {
                            add(draft)
                        } label: {
                            Label("Add \"\(KeywordTags.cleaned(draft))\" as new keyword", systemImage: "plus")
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(.horizontal, 10).padding(.vertical, 7)
                        }
                        .buttonStyle(.plain)
                    }
                }
                .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 8))
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(.white.opacity(0.12)))
            }
            HStack {
                Text("Keyword bank").font(.caption.weight(.medium))
                Text("Most used first").font(.caption2).foregroundStyle(.secondary)
                Spacer()
                if bank.count > 12 {
                    Button(showAllKeywords ? "Show fewer" : "Show all (\(bank.count))") {
                        showAllKeywords.toggle()
                    }
                    .buttonStyle(.plain).font(.caption).foregroundStyle(.cyan)
                }
            }
            if suggestions.isEmpty {
                Text("Keywords saved with events will appear here.")
                    .font(.caption).foregroundStyle(.secondary)
            } else if bank.isEmpty {
                Text("All bank keywords added.").font(.caption).foregroundStyle(.secondary)
            } else {
                ScrollView {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 140), alignment: .leading)], alignment: .leading, spacing: 6) {
                        ForEach(visibleBank, id: \.normalizedValue) { keyword in
                            Button {
                                add(keyword.displayValue, clearDraft: false)
                            } label: {
                                Label(keyword.displayValue, systemImage: "plus")
                                    .font(.caption).lineLimit(1)
                                    .padding(.horizontal, 9).padding(.vertical, 5)
                                    .background(.white.opacity(0.06), in: Capsule())
                            }
                            .buttonStyle(.plain)
                            .help("Add \(keyword.displayValue) · used in \(keyword.usageCount) events")
                            .accessibilityLabel("Add keyword \(keyword.displayValue)")
                        }
                    }
                }
                .frame(maxHeight: showAllKeywords ? 180 : 96)
            }
        }
        .onChange(of: draft) { _, value in
            highlighted = -1
            showSuggestions = true
            guard value.contains(",") else { return }
            let parts = value.split(separator: ",", omittingEmptySubsequences: false)
            for part in parts.dropLast() { add(String(part), clearDraft: false) }
            draft = String(parts.last ?? "").trimmingCharacters(in: .whitespaces)
        }
        .onChange(of: inputFocused) { _, focused in
            if !focused { showSuggestions = false }
        }
    }

    private func commitHighlightedOrDraft() {
        if showSuggestions && !matches.isEmpty {
            add(matches[max(highlighted, 0)].displayValue)
        } else {
            add(draft)
        }
    }

    private func add(_ value: String, clearDraft: Bool = true) {
        tags = KeywordTags.canonicalized(tags + [value], using: suggestions)
        if clearDraft { draft = "" }
        inputFocused = true
    }
}
