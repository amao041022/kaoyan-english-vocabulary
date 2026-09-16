// 离线试卷识别引擎（macOS）。
//   ocr <图片或PDF> [--dpi 200] [--lang en-US] [--fast]
//   render <PDF> --out <目录> --dpi 150 [--first 1] [--last 8]
//   probe
// 输出 JSON 到 stdout；不联网，不写除 render 目标目录以外的文件。
import Foundation
import AppKit
import Vision
import PDFKit
import CoreImage

// MARK: - 输出小工具

func fail(_ message: String) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(2)
}

func emit(_ object: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]) else {
        fail("JSON 序列化失败")
    }
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write("\n".data(using: .utf8)!)
}

// MARK: - 参数

var arguments = Array(CommandLine.arguments.dropFirst())
guard let command = arguments.first else { fail("缺少子命令：ocr / render / probe") }
arguments.removeFirst()

func value(of flag: String) -> String? {
    guard let index = arguments.firstIndex(of: flag), index + 1 < arguments.count else { return nil }
    return arguments[index + 1]
}

func intValue(_ flag: String, _ fallback: Int) -> Int {
    guard let raw = value(of: flag), let number = Int(raw) else { return fallback }
    return number
}

// MARK: - PDF 渲染

func renderPDF(path: String, outDir: String, dpi: Int, first: Int, last: Int) -> [[String: Any]] {
    guard let document = PDFDocument(url: URL(fileURLWithPath: path)) else { fail("无法打开 PDF：\(path)") }
    try? FileManager.default.createDirectory(atPath: outDir, withIntermediateDirectories: true)
    let scale = CGFloat(dpi) / 72.0
    var written: [[String: Any]] = []
    let start = max(1, first)
    let end = min(document.pageCount, last >= start ? last : document.pageCount)
    for number in start...max(start, end) {
        guard let page = document.page(at: number - 1) else { continue }
        let box = page.bounds(for: .mediaBox)
        let width = Int((box.width * scale).rounded()), height = Int((box.height * scale).rounded())
        guard width > 0, height > 0,
              let context = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8,
                                      bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                                      bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { continue }
        context.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
        context.fill(CGRect(x: 0, y: 0, width: width, height: height))
        context.scaleBy(x: scale, y: scale)
        context.translateBy(x: -box.origin.x, y: -box.origin.y)
        page.draw(with: .mediaBox, to: context)
        guard let image = context.makeImage() else { continue }
        let target = URL(fileURLWithPath: outDir).appendingPathComponent(String(format: "page-%03d.png", number))
        guard let destination = CGImageDestinationCreateWithURL(target as CFURL, "public.png" as CFString, 1, nil) else { continue }
        CGImageDestinationAddImage(destination, image, nil)
        CGImageDestinationFinalize(destination)
        written.append(["page": number, "path": target.path, "width": width, "height": height])
    }
    return written
}

func pdfToImages(path: String, dpi: Int) -> [CGImage] {
    guard let document = PDFDocument(url: URL(fileURLWithPath: path)) else { fail("无法打开 PDF：\(path)") }
    let scale = CGFloat(dpi) / 72.0
    var images: [CGImage] = []
    for index in 0..<document.pageCount {
        guard let page = document.page(at: index) else { continue }
        let box = page.bounds(for: .mediaBox)
        let width = Int((box.width * scale).rounded()), height = Int((box.height * scale).rounded())
        guard width > 0, height > 0,
              let context = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8,
                                      bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                                      bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { continue }
        context.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
        context.fill(CGRect(x: 0, y: 0, width: width, height: height))
        context.scaleBy(x: scale, y: scale)
        context.translateBy(x: -box.origin.x, y: -box.origin.y)
        page.draw(with: .mediaBox, to: context)
        if let image = context.makeImage() { images.append(image) }
    }
    return images
}

// MARK: - OCR

func recognise(_ image: CGImage, language: String, accurate: Bool) -> [[String: Any]] {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = accurate ? .accurate : .fast
    request.recognitionLanguages = [language]
    request.usesLanguageCorrection = true
    if #available(macOS 13.0, *) { request.automaticallyDetectsLanguage = false }
    request.minimumTextHeight = 0.006
    let handler = VNImageRequestHandler(cgImage: image, options: [:])
    do { try handler.perform([request]) } catch { fail("文字识别失败：\(error.localizedDescription)") }
    var rows: [[String: Any]] = []
    for observation in request.results ?? [] {
        guard let candidate = observation.topCandidates(1).first else { continue }
        let box = observation.boundingBox   // 归一化，原点在左下
        var alternatives: [String] = []
        for other in observation.topCandidates(3).dropFirst() where other.string != candidate.string {
            alternatives.append(other.string)
        }
        rows.append([
            "text": candidate.string,
            "confidence": Double(candidate.confidence),
            "x": Double(box.origin.x), "y": Double(box.origin.y),
            "w": Double(box.size.width), "h": Double(box.size.height),
            "alternatives": alternatives,
        ])
    }
    return rows
}

/// 采样每个文本行的像素，估计墨色：彩色墨迹（蓝/红笔）与黑色印刷体区分开。
func colourStats(_ image: CGImage, boxes: [[String: Any]]) -> [[String: Any]] {
    let width = image.width, height = image.height
    guard let context = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8,
                                  bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(),
                                  bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return boxes }
    context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
    guard let buffer = context.data else { return boxes }
    let pixels = buffer.bindMemory(to: UInt8.self, capacity: width * height * 4)
    var output: [[String: Any]] = []
    for var row in boxes {
        guard let x = row["x"] as? Double, let y = row["y"] as? Double,
              let w = row["w"] as? Double, let h = row["h"] as? Double else { output.append(row); continue }
        let x0 = max(0, Int(x * Double(width))), x1 = min(width, Int((x + w) * Double(width)))
        let y0 = max(0, Int((1 - y - h) * Double(height))), y1 = min(height, Int((1 - y) * Double(height)))
        var blue = 0, red = 0, grey = 0, total = 0
        var step = 1
        if (x1 - x0) * (y1 - y0) > 40000 { step = 2 }
        var py = y0
        while py < y1 {
            var px = x0
            while px < x1 {
                let offset = (py * width + px) * 4
                let r = Int(pixels[offset]), g = Int(pixels[offset + 1]), b = Int(pixels[offset + 2])
                let bright = (r + g + b) / 3
                if bright < 200 {
                    total += 1
                    if b - r > 22 && b - g > 12 { blue += 1 }
                    else if r - b > 22 && r - g > 12 { red += 1 }
                    else { grey += 1 }
                }
                px += step
            }
            py += step
        }
        let denominator = max(1, total)
        row["inkPixels"] = total
        row["blueRatio"] = Double(blue) / Double(denominator)
        row["redRatio"] = Double(red) / Double(denominator)
        row["greyRatio"] = Double(grey) / Double(denominator)
        output.append(row)
    }
    return output
}

// MARK: - 主流程

struct PageImage {
    let page: Int
    let image: CGImage
}

/// 手机照片动辄 3000×4000，直接送进 Vision 又慢又无必要；按长边缩放，保留文字可读性。
func downscale(_ image: CGImage, longEdge: Int) -> CGImage {
    let current = max(image.width, image.height)
    guard longEdge > 0, current > longEdge else { return image }
    let ratio = Double(longEdge) / Double(current)
    let width = Int((Double(image.width) * ratio).rounded())
    let height = Int((Double(image.height) * ratio).rounded())
    guard width > 0, height > 0,
          let context = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8,
                                  bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                                  bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { return image }
    context.interpolationQuality = .high
    context.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
    context.fill(CGRect(x: 0, y: 0, width: width, height: height))
    context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
    return context.makeImage() ?? image
}

func loadImages(path: String, dpi: Int, longEdge: Int) -> [PageImage] {
    let url = URL(fileURLWithPath: path)
    if url.pathExtension.lowercased() == "pdf" {
        return pdfToImages(path: path, dpi: dpi).enumerated().map {
            PageImage(page: $0.offset + 1, image: downscale($0.element, longEdge: longEdge))
        }
    }
    guard let image = NSImage(contentsOf: url),
          let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        fail("无法读取图片：\(path)")
    }
    return [PageImage(page: 1, image: downscale(cg, longEdge: longEdge))]
}

/// 输出整页灰度图 + 笔画长度图，交给 Python 做墨迹与圈画几何分析。
/// 笔画图是 8 位灰度：数值越大表示该点的水平/垂直笔画越长。
/// 印刷字母笔画短，手写圈线长，据此可以把印刷正文从笔迹里分出来。
func grayscalePNG(_ image: CGImage, target: URL) -> Bool {
    let width = image.width, height = image.height
    guard let context = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8,
                                  bytesPerRow: width, space: CGColorSpaceCreateDeviceGray(),
                                  bitmapInfo: CGImageAlphaInfo.none.rawValue) else { return false }
    context.setFillColor(CGColor(gray: 1, alpha: 1))
    context.fill(CGRect(x: 0, y: 0, width: width, height: height))
    context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
    guard let grey = context.makeImage(),
          let destination = CGImageDestinationCreateWithURL(target as CFURL, "public.png" as CFString, 1, nil)
    else { return false }
    CGImageDestinationAddImage(destination, grey, nil)
    return CGImageDestinationFinalize(destination)
}

func strokeMapPNG(_ image: CGImage, target: URL) -> Bool {
    let width = image.width, height = image.height
    guard let greyContext = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8,
                                      bytesPerRow: width, space: CGColorSpaceCreateDeviceGray(),
                                      bitmapInfo: CGImageAlphaInfo.none.rawValue) else { return false }
    greyContext.setFillColor(CGColor(gray: 1, alpha: 1))
    greyContext.fill(CGRect(x: 0, y: 0, width: width, height: height))
    greyContext.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
    guard let greyImage = greyContext.makeImage(),
          let data = greyContext.data else { return false }
    let pixels = data.bindMemory(to: UInt8.self, capacity: width * height)
    let inkThreshold: UInt8 = 165
    // 水平与垂直的连续墨迹长度，取较大值
    var horizontal = [Int32](repeating: 0, count: width * height)
    var stroke = [UInt8](repeating: 0, count: width * height)
    for y in 0..<height {
        let row = y * width
        var run = 0
        for x in 0..<width {
            if pixels[row + x] < inkThreshold { run += 1 } else { run = 0 }
            horizontal[row + x] = Int32(run)
        }
        var carry = 0
        for x in stride(from: width - 1, through: 0, by: -1) {
            let value = Int(horizontal[row + x])
            carry = value > 0 ? max(value, carry) : 0
            horizontal[row + x] = Int32(carry)
        }
    }
    for x in 0..<width {
        var run = 0
        for y in 0..<height {
            let index = y * width + x
            if pixels[index] < inkThreshold { run += 1 } else { run = 0 }
            let combined = max(Int(horizontal[index]), run)
            stroke[index] = UInt8(min(255, combined))
        }
    }
    let output = stroke.withUnsafeBytes { raw -> Data in
        Data(bytes: raw.baseAddress!, count: raw.count)
    }
    guard let provider = CGDataProvider(data: output as CFData),
          let strokeImage = CGImage(width: width, height: height, bitsPerComponent: 8,
                                    bitsPerPixel: 8, bytesPerRow: width,
                                    space: CGColorSpaceCreateDeviceGray(),
                                    bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.none.rawValue),
                                    provider: provider, decode: nil, shouldInterpolate: false,
                                    intent: .defaultIntent),
          let destination = CGImageDestinationCreateWithURL(target as CFURL, "public.png" as CFString, 1, nil)
    else { return false }
    CGImageDestinationAddImage(destination, strokeImage, nil)
    return CGImageDestinationFinalize(destination)
}

func jpeg(_ image: CGImage, target: URL, quality: Double = 0.82) -> Bool {
    guard let destination = CGImageDestinationCreateWithURL(target as CFURL, "public.jpeg" as CFString, 1, nil)
    else { return false }
    CGImageDestinationAddImage(destination, image,
                               [kCGImageDestinationLossyCompressionQuality: quality] as CFDictionary)
    return CGImageDestinationFinalize(destination)
}

switch command {
case "probe":
    emit(["ok": true, "engine": "apple-vision", "macOS": ProcessInfo.processInfo.operatingSystemVersionString])

case "render":
    guard let input = arguments.first else { fail("render 需要 PDF 路径") }
    guard let outDir = value(of: "--out") else { fail("render 需要 --out 目录") }
    let pages = renderPDF(path: input, outDir: outDir, dpi: intValue("--dpi", 150),
                          first: intValue("--first", 1), last: intValue("--last", Int.max))
    emit(["pages": pages])

case "ocr":
    guard let input = arguments.first else { fail("ocr 需要图片或 PDF 路径") }
    guard let workDir = value(of: "--work-dir") else { fail("ocr 需要 --work-dir 目录") }
    let dpi = intValue("--dpi", 200)
    let longEdge = intValue("--max-edge", 2400)
    let language = value(of: "--lang") ?? "en-US"
    let accurate = !arguments.contains("--fast")
    let first = intValue("--first", 1)
    let last = intValue("--last", Int.max)
    try? FileManager.default.createDirectory(atPath: workDir, withIntermediateDirectories: true)
    var pages: [[String: Any]] = []
    for entry in loadImages(path: input, dpi: dpi, longEdge: longEdge) {
        if entry.page < first || entry.page > last { continue }
        var rows = recognise(entry.image, language: language, accurate: accurate)
        rows = colourStats(entry.image, boxes: rows)
        let stem = String(format: "page-%03d", entry.page)
        let maskURL = URL(fileURLWithPath: workDir).appendingPathComponent(stem + "-ink.png")
        let strokeURL = URL(fileURLWithPath: workDir).appendingPathComponent(stem + "-stroke.png")
        let imageURL = URL(fileURLWithPath: workDir).appendingPathComponent(stem + ".jpg")
        _ = grayscalePNG(entry.image, target: maskURL)
        _ = strokeMapPNG(entry.image, target: strokeURL)
        _ = jpeg(entry.image, target: imageURL)
        pages.append(["page": entry.page, "width": entry.image.width, "height": entry.image.height,
                      "mask": maskURL.path, "stroke": strokeURL.path, "image": imageURL.path,
                      "lines": rows])
    }
    emit(["engine": "apple-vision", "dpi": dpi, "longEdge": longEdge, "pages": pages])

default:
    fail("未知子命令：\(command)")
}
