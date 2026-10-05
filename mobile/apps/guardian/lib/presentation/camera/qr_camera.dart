/// The camera behind the gate scanner, kept behind a small interface so the
/// scanner screen is tested without hardware (test/camera_test.dart).
///
/// Implementation: mobile_scanner (CameraX + bundled ML Kit barcode model:
/// works offline, minSdk 23 <= our 29). Only QR codes are decoded, only the
/// decoded TEXT leaves this class: `returnImage` stays false, no frame is
/// stored, nothing but the token is ever sent (to the existing endpoint).
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

enum QrCameraFailure {
  /// Camera permission refused (or revoked from the settings).
  permissionDenied,

  /// No camera, or held by another app.
  unavailable,

  /// Anything else reported by the camera stack.
  other,
}

class QrCameraException implements Exception {
  const QrCameraException(this.failure, [this.detail]);

  final QrCameraFailure failure;
  final String? detail;

  @override
  String toString() => 'QrCameraException($failure${detail == null ? '' : ': $detail'})';
}

abstract class QrCamera {
  /// Raw text of every QR seen while running.
  Stream<String> get codes;

  /// Starts the preview and the analysis; asks the camera permission the
  /// first time. Throws [QrCameraException].
  Future<void> start();

  Future<void> stop();

  Future<void> toggleTorch();

  Future<void> dispose();

  /// The live preview (must be in the tree before [start]).
  Widget preview(BuildContext context);
}

class MobileScannerQrCamera implements QrCamera {
  final _controller = MobileScannerController(
    autoStart: false, // the screen decides (lifecycle, timeout)
    formats: const [BarcodeFormat.qrCode],
    detectionSpeed: DetectionSpeed.noDuplicates,
    returnImage: false, // never a picture: text only
  );

  @override
  Stream<String> get codes =>
      _controller.barcodes.expand((capture) => capture.barcodes.map((b) => b.rawValue).whereType<String>());

  @override
  Future<void> start() async {
    try {
      await _controller.start();
    } on MobileScannerException catch (error) {
      throw _map(error);
    }
    // Platform failures are reported in the state, not thrown.
    final error = _controller.value.error;
    if (error != null && !_controller.value.isRunning) throw _map(error);
  }

  @override
  Future<void> stop() => _controller.stop();

  @override
  Future<void> toggleTorch() => _controller.toggleTorch();

  @override
  Future<void> dispose() => _controller.dispose();

  @override
  Widget preview(BuildContext context) => MobileScanner(
    controller: _controller,
    fit: BoxFit.cover,
    // Errors are shown by the scanner screen itself.
    errorBuilder: (context, error) => const ColoredBox(color: Colors.black),
  );

  static QrCameraException _map(MobileScannerException error) => QrCameraException(switch (error.errorCode) {
    MobileScannerErrorCode.permissionDenied => QrCameraFailure.permissionDenied,
    MobileScannerErrorCode.unsupported => QrCameraFailure.unavailable,
    _ => QrCameraFailure.other,
  }, error.errorDetails?.message);
}
