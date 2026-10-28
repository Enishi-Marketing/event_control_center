import Foundation

private struct ProbePayload: Encodable {
    let mode: String
}

@main
struct BackendStreamProbe {
    static func main() async {
        do {
            let client = try BackendClient()
            let mode = CommandLine.arguments[1]
            if mode == "real-import" {
                let payload = ImportMediaPayload(
                    source: CommandLine.arguments[2], eventFolder: CommandLine.arguments[3],
                    sessionGapMinutes: 20, sessionIndexes: [1],
                    eventName: "Native video test", brightness: 0
                )
                for try await event in try client.importEvents(payload: payload) {
                    let data = try JSONEncoder().encode(event)
                    FileHandle.standardOutput.write(data + Data([0x0A]))
                }
                FileHandle.standardOutput.write(Data("finished\n".utf8))
                return
            }
            let count = Int(CommandLine.arguments.dropFirst(2).first ?? "1") ?? 1
            try await withThrowingTaskGroup(of: Int.self) { group in
                for _ in 0..<count {
                    group.addTask {
                        let events = try client.socialVideoEvents(payload: ProbePayload(mode: mode))
                        var received = 0
                        for try await event in events {
                            received += 1
                            let data = try JSONEncoder().encode(event)
                            FileHandle.standardOutput.write(data + Data([0x0A]))
                        }
                        return received
                    }
                }
                for try await received in group {
                    FileHandle.standardOutput.write(Data("finished: \(received)\n".utf8))
                }
            }
        } catch {
            FileHandle.standardError.write(Data("\(error.localizedDescription)\n".utf8))
            exit(1)
        }
    }
}
