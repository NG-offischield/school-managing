import 'dart:io';
import 'dart:typed_data';

import 'package:path_provider/path_provider.dart';

/// Where downloaded official PDFs (report cards, receipts) are kept: the
/// app's private storage. The PDF itself comes from the server, with the
/// school's branding — never the software's.
abstract class PdfStore {
  const PdfStore();

  /// Saves [bytes] under [name]; returns where it was written.
  Future<String> save(String name, Uint8List bytes);
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
}

/// Tests: keeps the files in memory.
class MemoryPdfStore extends PdfStore {
  MemoryPdfStore();

  final files = <String, Uint8List>{};

  @override
  Future<String> save(String name, Uint8List bytes) async {
    files[name] = bytes;
    return 'memory://$name';
  }
}
