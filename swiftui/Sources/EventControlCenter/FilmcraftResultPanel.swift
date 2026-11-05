import AppKit
import SwiftUI

struct FilmcraftResultPanel: View {
    let result: FilmcraftResult

    private var needsReview: Bool { !result.failures.isEmpty || !result.proxyProblems.isEmpty }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(needsReview ? "FilmCraft needs attention" : (result.unchanged ? "FilmCraft is up to date" : "FilmCraft preparation complete"),
                  systemImage: needsReview ? "exclamationmark.triangle.fill" : "film.stack")
                .foregroundStyle(needsReview ? Color.orange : Color.green)
            Text("\(result.videos) videos · \(result.photos) photos · \(result.proxiesLinked) proxies linked · \(result.proxyProblems.count) proxy problems")
            Text("\(result.timelinesCreated) timelines created · \(result.timelinesUpdated) updated")
            if result.intermediatePhotos > 0 {
                Text("\(result.intermediatePhotos) photos use full-resolution intermediates for FilmCraft compatibility. Originals remain in Raw/Photos.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            ForEach(Array((result.failures + result.proxyProblems).prefix(8).enumerated()), id: \.offset) { _, message in
                Text(message).font(.callout).foregroundStyle(.orange).textSelection(.enabled)
            }
            ForEach(Array(result.warnings.enumerated()), id: \.offset) { _, message in
                Text(message).font(.caption).foregroundStyle(.secondary)
            }
            if !result.projectPath.isEmpty {
                Text(result.projectPath).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                HStack {
                    if result.photos + result.videos > 0 {
                        Button("Open prepared project") { NSWorkspace.shared.open(URL(fileURLWithPath: result.projectPath)) }
                    }
                    Button("Open preparation report") {
                        let event = URL(fileURLWithPath: result.projectPath).deletingLastPathComponent().deletingLastPathComponent()
                        NSWorkspace.shared.open(event.appendingPathComponent("Data/FilmCraft/last_result.json"))
                    }
                }
            }
        }
    }
}
