/// School plans (backend documents/plans_api.py): the 2D plans the school
/// imported (PDF / PNG / JPEG) and published for its parents and teachers.
/// Read only; the server decides, at EVERY request, who may see which plan
/// (AUTO / MANUAL distribution) — an unauthorised plan is a 404.
///
///   GET /plans/   GET /plans/{id}/   GET /plans/{id}/file/  (bytes of the published version)
library;

import 'dart:io';
import 'dart:typed_data';

import '../config/local_network.dart';
import 'communication.dart';

class SchoolPlan {
  SchoolPlan({
    required this.id,
    required this.title,
    required this.description,
    required this.building,
    required this.floor,
    required this.schoolName,
    required this.number,
    required this.mimeType,
    required this.sizeBytes,
    this.width,
    this.height,
    this.pageCount,
    this.publishedAt,
  });

  factory SchoolPlan.fromJson(Map<String, dynamic> json) {
    final version = ((json['version'] as Map?) ?? const {}).cast<String, dynamic>();
    return SchoolPlan(
      id: '${json['id']}',
      title: (json['title'] as String?) ?? '',
      description: (json['description'] as String?) ?? '',
      building: (json['building'] as String?) ?? '',
      floor: (json['floor'] as String?) ?? '',
      schoolName: (json['school_name'] as String?) ?? '',
      number: (version['number'] as int?) ?? 0,
      mimeType: (version['mime_type'] as String?) ?? '',
      sizeBytes: (version['size_bytes'] as int?) ?? 0,
      width: version['width'] as int?,
      height: version['height'] as int?,
      pageCount: version['page_count'] as int?,
      publishedAt: schoolTime(version['published_at'] ?? json['published_at']),
    );
  }

  final String id;
  final String title;
  final String description;
  final String building;
  final String floor;
  final String schoolName;

  /// The published version (the only one a reader ever gets).
  final int number;
  final String mimeType;
  final int sizeBytes;
  final int? width;
  final int? height;
  final int? pageCount;
  final DateTime? publishedAt;

  bool get isPdf => mimeType == 'application/pdf';
  bool get isImage => mimeType == 'image/png' || mimeType == 'image/jpeg';

  /// "Bâtiment A · RDC", "" when neither is set.
  String get location => [building, floor].where((p) => p.isNotEmpty).join(' · ');

  /// "PDF · 2 pages · 1,2 Mo", "PNG · 4000 × 3000 px · 850 Ko".
  String get details {
    final kind = isPdf ? 'PDF' : (mimeType == 'image/png' ? 'PNG' : 'JPEG');
    final shape = isPdf
        ? (pageCount == null ? null : '$pageCount page${pageCount! > 1 ? 's' : ''}')
        : (width == null || height == null ? null : '$width × $height px');
    return [kind, ?shape, sizeLabel(sizeBytes)].join(' · ');
  }
}

String sizeLabel(int bytes) {
  if (bytes < 1024 * 1024) return '${(bytes / 1024).ceil()} Ko';
  return '${(bytes / (1024 * 1024)).toStringAsFixed(1).replaceAll('.', ',')} Mo';
}

/// Where a downloaded PDF plan goes to be shown by the phone's viewer. The
/// copy lives only in the app's cache: written, handed to [openDocument]
/// (which shares a copy from cache/shared/ only), then deleted. [clear] runs
/// on a server switch / session leave: nothing of the old school stays.
abstract class PlanFiles {
  const PlanFiles();

  /// Shows [bytes] (a PDF) with the phone's viewer; false when none can.
  Future<bool> openPdf(String name, Uint8List bytes);

  Future<void> clear();
}

class DevicePlanFiles extends PlanFiles {
  const DevicePlanFiles({this.root});

  /// The app's cache (Directory.systemTemp on Android); injectable in tests.
  final Directory? root;

  Directory get _folder => Directory('${(root ?? Directory.systemTemp).path}/plans');

  @override
  Future<bool> openPdf(String name, Uint8List bytes) async {
    await _folder.create(recursive: true);
    final safe = name.replaceAll(RegExp(r'[^A-Za-z0-9._-]'), '_');
    final file = File('${_folder.path}/$safe');
    await file.writeAsBytes(bytes, flush: true);
    try {
      return await openDocument(file.path);
    } finally {
      if (await file.exists()) await file.delete(); // the viewer got its own copy (cache/shared/)
    }
  }

  @override
  Future<void> clear() async {
    if (await _folder.exists()) await _folder.delete(recursive: true);
    await clearSharedDocuments(); // the copies handed to the viewer
  }
}

/// Tests: nothing written.
class MemoryPlanFiles extends PlanFiles {
  MemoryPlanFiles();

  final opened = <String, Uint8List>{};

  /// false = a phone without any PDF viewer.
  bool canOpen = true;
  int cleared = 0;

  @override
  Future<bool> openPdf(String name, Uint8List bytes) async {
    opened[name] = bytes;
    return canOpen;
  }

  @override
  Future<void> clear() async {
    opened.clear();
    cleared++;
  }
}
