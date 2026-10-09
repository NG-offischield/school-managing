import 'dart:io';
import 'dart:typed_data';

import 'package:path_provider/path_provider.dart';
import 'package:school_core/school_core.dart';

/// Where downloaded official PDFs (report cards, receipts) are kept: the
/// app's private storage. The PDF itself comes from the server, with the
/// school's branding — never the software's.
abstract class PdfStore {
  const PdfStore();

  /// Saves [bytes] under [name]; returns where it was written.
  Future<String> save(String name, Uint8List bytes);

  /// Shows the saved file with the phone's PDF viewer; false when none can.
  Future<bool> open(String path);

  /// Server switch: the documents of the old school leave the phone.
  Future<void> clear();
}

class DevicePdfStore extends PdfStore {
  const DevicePdfStore();

  @override
  Future<String> save(String name, Uint8List bytes) async {
    final folder = Directory('${(await getApplicationDocumentsDirectory()).path}/documents');
    await folder.create(recursive: true);
    final safe = name.replaceAll(RegExp(r'[^A-Za-z0-9._-]'), '_');
    final file = File('${folder.path}/$safe');
    await file.writeAsBytes(bytes, flush: true);
    return file.path;
  }

  @override
  Future<bool> open(String path) => openDocument(path); // school_core: FileProvider, cache/shared/ only

  @override
  Future<void> clear() async {
    // documents/ (saved PDFs) and cache/shared/ (the copies handed to the PDF viewer).
    for (final folder in [
      Directory('${(await getApplicationDocumentsDirectory()).path}/documents'),
      Directory('${(await getTemporaryDirectory()).path}/shared'),
    ]) {
      if (await folder.exists()) await folder.delete(recursive: true);
    }
  }
}

/// Tests: keeps the files in memory.
class MemoryPdfStore extends PdfStore {
  MemoryPdfStore();

  final files = <String, Uint8List>{};
  final opened = <String>[];

  /// false = a phone without any PDF viewer.
  bool canOpen = true;

  @override
  Future<bool> open(String path) async {
    opened.add(path);
    return canOpen;
  }

  @override
  Future<String> save(String name, Uint8List bytes) async {
    files[name] = bytes;
    return 'memory://$name';
  }

  @override
  Future<void> clear() async {
    files.clear();
    opened.clear();
  }
}
