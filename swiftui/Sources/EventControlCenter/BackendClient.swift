import Foundation

enum BackendError: LocalizedError {
    case unavailable(String)
    case failed(String)
    case invalidResponse

    var errorDescription: String? {
        switch self {
        case .unavailable(let message), .failed(let message): message
        case .invalidResponse: "The Python backend returned an unreadable response."
        }
    }
}

struct BackendClient {
    private let rootURL: URL
    private let pythonURL: URL

    init() throws {
        let environment = ProcessInfo.processInfo.environment
        let fileManager = FileManager.default
        let candidateRoots: [String] = [
            environment["ECC_BACKEND_ROOT"],
            Bundle.main.resourceURL?.path,
            fileManager.currentDirectoryPath,
            URL(fileURLWithPath: fileManager.currentDirectoryPath).deletingLastPathComponent().path,
        ].compactMap { $0 }

        guard let root = candidateRoots
            .map({ URL(fileURLWithPath: $0) })
            .first(where: { fileManager.fileExists(atPath: $0.appendingPathComponent("backend_bridge.py").path) })
        else {
            throw BackendError.unavailable("Could not find backend_bridge.py. Set ECC_BACKEND_ROOT to the Event Control Center folder.")
        }

        rootURL = root
        pythonURL = try Self.findCompatiblePython(
            rootURL: rootURL,
            configuredPython: environment["ECC_PYTHON"],
            fileManager: fileManager
        )
    }

    func request<Payload: Encodable, Result: Decodable>(
        _ command: String,
        payload: Payload
    ) async throws -> Result {
        let request = Request(command: command, payload: payload)
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let body = try encoder.encode(request)
        return try await Task.detached(priority: .userInitiated) {
            let process = Process()
            process.executableURL = pythonURL
            process.arguments = [rootURL.appendingPathComponent("backend_bridge.py").path]
            process.currentDirectoryURL = rootURL

            let input = Pipe()
            let output = Pipe()
            let errors = Pipe()
            process.standardInput = input
            process.standardOutput = output
            process.standardError = errors

            do {
                try process.run()
            } catch {
                throw BackendError.unavailable("Could not start Python at \(pythonURL.path). Set ECC_PYTHON to this app's configured Python interpreter.")
            }
            input.fileHandleForWriting.write(body)
            try? input.fileHandleForWriting.close()
            let responseData = output.fileHandleForReading.readDataToEndOfFile()
            let errorData = errors.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()

            guard !responseData.isEmpty else {
                let detail = String(data: errorData, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                throw BackendError.failed(detail.isEmpty ? "The Python backend did not return a result." : detail)
            }
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            guard let response = try? decoder.decode(BackendEnvelope<Result>.self, from: responseData) else {
                throw BackendError.invalidResponse
            }
            guard response.ok, let value = response.data else {
                throw BackendError.failed(response.error ?? "The Python backend could not complete this action.")
            }
            return value
        }.value
    }

    func importEvents(
        payload: ImportMediaPayload
    ) throws -> AsyncThrowingStream<ImportStreamEvent, Error> {
        let request = Request(command: "import_media_stream", payload: payload)
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let body = try encoder.encode(request)

        return AsyncThrowingStream { continuation in
            Task.detached(priority: .userInitiated) {
                let process = Process()
                process.executableURL = pythonURL
                process.arguments = [rootURL.appendingPathComponent("backend_bridge.py").path]
                process.currentDirectoryURL = rootURL

                let input = Pipe()
                let output = Pipe()
                let errors = Pipe()
                process.standardInput = input
                process.standardOutput = output
                process.standardError = errors

                do {
                    try process.run()
                    input.fileHandleForWriting.write(body)
                    try? input.fileHandleForWriting.close()

                    let decoder = JSONDecoder()
                    decoder.keyDecodingStrategy = .convertFromSnakeCase
                    for try await line in output.fileHandleForReading.bytes.lines {
                        guard let data = line.data(using: .utf8) else { continue }
                        let event = try decoder.decode(ImportStreamEvent.self, from: data)
                        continuation.yield(event)
                    }
                    process.waitUntilExit()
                    if process.terminationStatus != 0 {
                        let message = String(
                            data: errors.fileHandleForReading.readDataToEndOfFile(),
                            encoding: .utf8
                        ) ?? "Import process stopped unexpectedly."
                        continuation.finish(throwing: BackendError.failed(message))
                    } else {
                        continuation.finish()
                    }
                } catch {
                    continuation.finish(throwing: error)
                }
            }
        }
    }

    private struct Request<Payload: Encodable>: Encodable {
        let command: String
        let payload: Payload
    }

    private static func findCompatiblePython(
        rootURL: URL,
        configuredPython: String?,
        fileManager: FileManager
    ) throws -> URL {
        let candidates = [
            configuredPython,
            rootURL.appendingPathComponent(".venv/bin/python").path,
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
            "/usr/bin/python3",
        ].compactMap { $0 }

        var checked: Set<String> = []
        for path in candidates where checked.insert(path).inserted {
            guard fileManager.isExecutableFile(atPath: path) else { continue }
            if isPython310OrNewer(at: URL(fileURLWithPath: path)) {
                return URL(fileURLWithPath: path)
            }
        }

        throw BackendError.unavailable(
            "A compatible Python 3.10 or newer installation was not found. " +
            "Install the project requirements in .venv, or set ECC_PYTHON to that interpreter."
        )
    }

    private static func isPython310OrNewer(at pythonURL: URL) -> Bool {
        let process = Process()
        let output = Pipe()
        process.executableURL = pythonURL
        process.arguments = ["-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"]
        process.standardOutput = output
        process.standardError = Pipe()

        do {
            try process.run()
            process.waitUntilExit()
            guard process.terminationStatus == 0,
                  let version = String(
                    data: output.fileHandleForReading.readDataToEndOfFile(),
                    encoding: .utf8
                  )?.trimmingCharacters(in: .whitespacesAndNewlines)
            else { return false }

            let components = version.split(separator: ".").compactMap { Int($0) }
            guard components.count == 2 else { return false }
            return components[0] > 3 || (components[0] == 3 && components[1] >= 10)
        } catch {
            return false
        }
    }
}

struct EmptyPayload: Codable {}
