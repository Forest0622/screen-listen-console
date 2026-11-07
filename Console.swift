import AppKit
import Foundation
import Darwin

let PORT = 6080
let DATA_DIR = NSHomeDirectory() + "/.remote-view"          // 每台机器的用户目录
let LOG_DIR = DATA_DIR + "/logs"
let CLIENTS_FILE = LOG_DIR + "/clients.json"
let BUNDLE_RES = Bundle.main.bundlePath + "/Contents/Resources"
let SERVER_PY = FileManager.default.isReadableFile(atPath: BUNDLE_RES + "/server.py")
    ? BUNDLE_RES + "/server.py"                              // 优先用 App 内置副本
    : DATA_DIR + "/server.py"
let AUTH_TEXT = "账号 admin    密码 2010622"

/// 找到可用的 python3（系统自带 / Homebrew / 命令行工具）
func pythonPath() -> String {
    let cands = ["/usr/bin/python3", "/opt/homebrew/bin/python3", "/usr/local/bin/python3",
                 "/Library/Developer/CommandLineTools/usr/bin/python3"]
    for c in cands where FileManager.default.isExecutableFile(atPath: c) { return c }
    return ""
}

// MARK: - 工具函数

func portOpen(_ port: Int) -> Bool {
    let fd = socket(AF_INET, SOCK_STREAM, 0)
    if fd < 0 { return false }
    defer { close(fd) }
    var addr = sockaddr_in()
    addr.sin_family = sa_family_t(AF_INET)
    addr.sin_port = in_port_t(UInt16(port).bigEndian)
    addr.sin_addr.s_addr = inet_addr("127.0.0.1")
    var a = addr
    let res = withUnsafePointer(to: &a) { p -> Int32 in
        p.withMemoryRebound(to: sockaddr.self, capacity: 1) { sa in
            Darwin.connect(fd, sa, socklen_t(MemoryLayout<sockaddr_in>.size))
        }
    }
    return res == 0
}

func runShell(_ launch: String, _ args: [String]) -> String {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: launch)
    p.arguments = args
    let pipe = Pipe()
    p.standardOutput = pipe
    p.standardError = pipe
    do { try p.run() } catch { return "" }
    p.waitUntilExit()
    let d = pipe.fileHandleForReading.readDataToEndOfFile()
    return String(data: d, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
}

func lanIP() -> String {
    for ifname in ["en0", "en1", "en2"] {
        let ip = runShell("/usr/bin/ipconfig", ["getifaddr", ifname])
        if !ip.isEmpty { return ip }
    }
    // 退一步：解析 ifconfig
    let out = runShell("/sbin/ifconfig", [])
    for line in out.split(separator: "\n") {
        let s = line.trimmingCharacters(in: .whitespaces)
        if s.hasPrefix("inet ") && !s.contains("127.0.0.1") {
            let parts = s.split(separator: " ")
            if parts.count > 1 { return String(parts[1]) }
        }
    }
    return "本机IP"
}

func localHostName() -> String {
    let n = runShell("/usr/sbin/scutil", ["--get", "LocalHostName"])
    return n.isEmpty ? "localhost" : n
}

func killListener() {
    let pids = runShell("/usr/sbin/lsof", ["-nP", "-iTCP:\(PORT)", "-sTCP:LISTEN"])
    for line in pids.split(separator: "\n").dropFirst() {
        let cols = line.split(separator: " ").map(String.init)
        if cols.count > 1, let pid = Int32(cols[1]) {
            kill(pid, SIGKILL)
        }
    }
}

// MARK: - 访问记录

struct Visit {
    let ip: String
    let first: Double
    let last: Double
    let count: Int
    let pages: Int
}

func loadVisits() -> [Visit] {
    guard let data = FileManager.default.contents(atPath: CLIENTS_FILE),
          let arr = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] else {
        return []
    }
    var out: [Visit] = []
    for o in arr {
        let ip = (o["ip"] as? String) ?? "?"
        let first = (o["first"] as? Double) ?? 0
        let last = (o["last"] as? Double) ?? 0
        let count = (o["count"] as? Int) ?? Int((o["count"] as? Double) ?? 0)
        let pages = (o["pages"] as? Int) ?? Int((o["pages"] as? Double) ?? 0)
        out.append(Visit(ip: ip, first: first, last: last, count: count, pages: pages))
    }
    return out.sorted { $0.last > $1.last }
}

func fmtClock(_ ts: Double) -> String {
    guard ts > 0 else { return "-" }
    let f = DateFormatter()
    f.dateFormat = "HH:mm:ss"
    return f.string(from: Date(timeIntervalSince1970: ts))
}

// MARK: - 界面

final class ConsoleView: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var statusDot: NSView!
    var statusLabel: NSTextField!
    var subLabel: NSTextField!
    var captureLabel: NSTextField!
    var startBtn: NSButton!
    var stopBtn: NSButton!
    var addrField: NSTextField!
    var visitsView: NSTextView!
    var visitsBox: NSScrollView!
    var lastMsg: NSTextField!
    var timer: Timer?
    var child: Process?

    func applicationDidFinishLaunching(_ n: Notification) {
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 520, height: 600),
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered, defer: false)
        window.title = "屏幕监听控制台"
        window.center()
        window.isReleasedWhenClosed = false
        let content = NSView(frame: NSRect(x: 0, y: 0, width: 520, height: 600))
        window.contentView = content

        // 标题
        let title = NSTextField(labelWithString: "屏幕监听服务")
        title.font = NSFont.boldSystemFont(ofSize: 20)
        title.frame = NSRect(x: 24, y: 548, width: 300, height: 26)
        content.addSubview(title)

        let tip = NSTextField(labelWithString: "本窗口只做启停与状态查看，不显示画面")
        tip.font = NSFont.systemFont(ofSize: 11)
        tip.textColor = .secondaryLabelColor
        tip.frame = NSRect(x: 24, y: 528, width: 460, height: 16)
        content.addSubview(tip)

        // 状态区
        let panel = NSBox(frame: NSRect(x: 20, y: 440, width: 480, height: 80))
        panel.boxType = .custom
        panel.borderType = .lineBorder
        panel.fillColor = NSColor.controlBackgroundColor
        panel.contentViewMargins = .zero
        content.addSubview(panel)

        statusDot = NSView(frame: NSRect(x: 18, y: 54, width: 12, height: 12))
        statusDot.wantsLayer = true
        statusDot.layer?.cornerRadius = 6
        panel.addSubview(statusDot)

        statusLabel = NSTextField(labelWithString: "服务已关闭")
        statusLabel.font = NSFont.boldSystemFont(ofSize: 16)
        statusLabel.frame = NSRect(x: 40, y: 50, width: 420, height: 22)
        panel.addSubview(statusLabel)

        subLabel = NSTextField(labelWithString: "监听端口 \(PORT)")
        subLabel.font = NSFont.systemFont(ofSize: 11)
        subLabel.textColor = .secondaryLabelColor
        subLabel.frame = NSRect(x: 40, y: 22, width: 420, height: 18)
        panel.addSubview(subLabel)

        captureLabel = NSTextField(labelWithString: "")
        captureLabel.font = NSFont.systemFont(ofSize: 11)
        captureLabel.frame = NSRect(x: 24, y: 414, width: 472, height: 18)
        content.addSubview(captureLabel)

        // 按钮
        startBtn = NSButton(title: "开启服务", target: self, action: #selector(startService))
        startBtn.bezelStyle = .rounded
        startBtn.keyEquivalent = "\r"
        startBtn.frame = NSRect(x: 20, y: 372, width: 150, height: 32)
        content.addSubview(startBtn)

        stopBtn = NSButton(title: "关闭服务", target: self, action: #selector(stopService))
        stopBtn.bezelStyle = .rounded
        stopBtn.frame = NSRect(x: 180, y: 372, width: 150, height: 32)
        content.addSubview(stopBtn)

        let refreshBtn = NSButton(title: "刷新状态", target: self, action: #selector(refreshNow))
        refreshBtn.bezelStyle = .rounded
        refreshBtn.frame = NSRect(x: 350, y: 372, width: 150, height: 32)
        content.addSubview(refreshBtn)

        // 访问地址
        let addrTitle = NSTextField(labelWithString: "设备访问地址")
        addrTitle.font = NSFont.boldSystemFont(ofSize: 13)
        addrTitle.frame = NSRect(x: 24, y: 344, width: 200, height: 18)
        content.addSubview(addrTitle)

        addrField = NSTextField(labelWithString: "")
        addrField.isSelectable = true
        addrField.font = NSFont.monospacedDigitSystemFont(ofSize: 12, weight: .regular)
        addrField.frame = NSRect(x: 24, y: 274, width: 472, height: 66)
        addrField.maximumNumberOfLines = 4
        addrField.lineBreakMode = .byWordWrapping
        addrField.cell?.wraps = true
        content.addSubview(addrField)

        let copyBtn = NSButton(title: "复制地址", target: self, action: #selector(copyAddresses))
        copyBtn.bezelStyle = .rounded
        copyBtn.frame = NSRect(x: 24, y: 240, width: 100, height: 26)
        content.addSubview(copyBtn)

        let openBtn = NSButton(title: "在本机打开", target: self, action: #selector(openLocal))
        openBtn.bezelStyle = .rounded
        openBtn.frame = NSRect(x: 134, y: 240, width: 110, height: 26)
        content.addSubview(openBtn)

        // 访问记录
        let recTitle = NSTextField(labelWithString: "设备访问记录（最近在前）")
        recTitle.font = NSFont.boldSystemFont(ofSize: 13)
        recTitle.frame = NSRect(x: 24, y: 212, width: 300, height: 18)
        content.addSubview(recTitle)

        visitsBox = NSScrollView(frame: NSRect(x: 22, y: 36, width: 476, height: 168))
        visitsBox.hasVerticalScroller = true
        visitsBox.borderType = .lineBorder
        let tv = NSTextView(frame: visitsBox.bounds)
        tv.isEditable = false
        tv.font = NSFont.monospacedSystemFont(ofSize: 11.5, weight: .regular)
        tv.textContainerInset = NSSize(width: 6, height: 6)
        visitsView = tv
        visitsBox.documentView = tv
        content.addSubview(visitsBox)

        lastMsg = NSTextField(labelWithString: "")
        lastMsg.font = NSFont.systemFont(ofSize: 11)
        lastMsg.textColor = .secondaryLabelColor
        lastMsg.frame = NSRect(x: 24, y: 6, width: 472, height: 18)
        content.addSubview(lastMsg)

        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        refreshNow()
        timer = Timer.scheduledTimer(withTimeInterval: 1.5, repeats: true) { [weak self] _ in
            self?.refreshNow()
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ s: NSApplication) -> Bool { true }

    // MARK: 动作

    @objc func startService() {
        if portOpen(PORT) {
            lastMsg.stringValue = "服务本来就在运行"
            refreshNow()
            return
        }
        let py = pythonPath()
        if py.isEmpty {
            lastMsg.stringValue = "未检测到 Python 3，请先在终端执行：xcode-select --install"
            return
        }
        if !FileManager.default.isReadableFile(atPath: SERVER_PY) {
            lastMsg.stringValue = "缺少服务脚本 server.py"
            return
        }
        try? FileManager.default.createDirectory(atPath: LOG_DIR, withIntermediateDirectories: true)
        let p = Process()
        p.executableURL = URL(fileURLWithPath: py)
        p.arguments = [SERVER_PY]
        p.currentDirectoryURL = URL(fileURLWithPath: DATA_DIR)
        var env = ProcessInfo.processInfo.environment
        env["RV_DATA_DIR"] = DATA_DIR
        p.environment = env
        let outURL = URL(fileURLWithPath: LOG_DIR + "/service.log")
        if let fh = try? FileHandle(forWritingTo: outURL) {
            fh.seekToEndOfFile()
            p.standardOutput = fh
            p.standardError = fh
        }
        do {
            try p.run()
            child = p
            lastMsg.stringValue = "已发送启动指令…"
        } catch {
            lastMsg.stringValue = "启动失败：\(error.localizedDescription)"
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) { self.refreshNow() }
    }

    @objc func stopService() {
        killListener()
        lastMsg.stringValue = "已停止服务"
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { self.refreshNow() }
    }

    @objc func refreshNow() {
        let running = portOpen(PORT)
        statusLabel.stringValue = running ? "服务已开启" : "服务已关闭"
        statusDot.layer?.backgroundColor = (running ? NSColor.systemGreen : NSColor.systemRed).cgColor
        subLabel.stringValue = running
            ? "监听端口 \(PORT) · 抓屏正常时可远程查看"
            : "端口 \(PORT) 未监听"
        startBtn.isEnabled = !running
        stopBtn.isEnabled = running

        let ip = lanIP()
        let host = localHostName()
        addrField.stringValue = running
            ? "本机：  http://127.0.0.1:\(PORT)/\n局域网：http://\(ip):\(PORT)/\n同域名：http://\(host).local:\(PORT)/\n\(AUTH_TEXT)"
            : "服务未开启，无可用地址\n（开启后这里会列出 3 个访问入口）"

        // 抓屏是否真的在工作（看最近一帧的生成时间）
        if running {
            let path = "/tmp/remoteview/frame.jpg"
            if let attr = try? FileManager.default.attributesOfItem(atPath: path),
               let mdate = attr[.modificationDate] as? Date {
                let age = Date().timeIntervalSince(mdate)
                if age < 15 {
                    captureLabel.stringValue = String(format: "抓屏状态：正常（最近一帧 %.0f 秒前）", age)
                    captureLabel.textColor = .secondaryLabelColor
                } else {
                    captureLabel.stringValue = "抓屏状态：异常（画面已停更 \(Int(age)) 秒，可能缺屏幕录制权限）"
                    captureLabel.textColor = .systemOrange
                }
            } else {
                captureLabel.stringValue = "抓屏状态：异常（没有生成画面，可能缺屏幕录制权限）"
                captureLabel.textColor = .systemOrange
            }
        } else {
            captureLabel.stringValue = "抓屏状态：—（服务未开启）"
            captureLabel.textColor = .secondaryLabelColor
        }

        let visits = loadVisits()
        if visits.isEmpty {
            visitsView.string = "暂无访问记录"
        } else {
            var lines = [String]()
            for v in visits.prefix(30) {
                let isLocal = v.ip.hasPrefix("127.")
                let tag = isLocal ? "本机" : "外部"
                lines.append(String(format: "%-15@ %@ %@ %d次(页%d)", v.ip as NSString, tag as NSString,
                                    fmtClock(v.last) as NSString, v.count, v.pages))
            }
            visitsView.string = lines.joined(separator: "\n")
        }
    }

    @objc func copyAddresses() {
        guard portOpen(PORT) else { return }
        let text = "http://\(lanIP()):\(PORT)/  \(AUTH_TEXT)"
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        lastMsg.stringValue = "局域网地址与账号已复制"
    }

    @objc func openLocal() {
        guard portOpen(PORT) else { return }
        if let url = URL(string: "http://127.0.0.1:\(PORT)/") {
            NSWorkspace.shared.open(url)
        }
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.regular)
let delegate = ConsoleView()
app.delegate = delegate
app.run()
