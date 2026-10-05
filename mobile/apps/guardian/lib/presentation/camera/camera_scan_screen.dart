/// Full-screen camera scanner of the gate. Returns the token of the FIRST
/// valid student-card QR (then closes), or null (back, cancel, manual entry).
///
/// - one read only: the first valid code locks the screen (no double scan),
///   light vibration, camera stopped, screen closed;
/// - a QR that is not a student card (URL, Wi-Fi...) is ignored with a
///   message and never sent anywhere;
/// - camera refused / revoked: explanation, ask again, app settings, or the
///   manual entry; no camera: manual entry;
/// - nothing read within [timeout]: the camera stops (battery), retry;
/// - background: camera released on pause, restarted on resume (the
///   permission is checked again then);
/// - back button / AppBar always leave the scanner.
/// No image is kept or sent: only the decoded text (see qr_camera.dart).
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:school_core/school_core.dart';

import 'qr_camera.dart';

enum _State { starting, scanning, denied, unavailable, failed, timedOut }

class CameraScanScreen extends StatefulWidget {
  const CameraScanScreen({super.key, required this.camera, this.timeout = const Duration(seconds: 45)});

  /// Creates the camera (tests: a fake one).
  final QrCamera Function() camera;
  final Duration timeout;

  /// Pushes the scanner; the token read, or null.
  static Future<String?> open(BuildContext context, QrCamera Function() camera) =>
      Navigator.of(context).push<String>(MaterialPageRoute(builder: (_) => CameraScanScreen(camera: camera)));

  @override
  State<CameraScanScreen> createState() => _CameraScanScreenState();
}

class _CameraScanScreenState extends State<CameraScanScreen> with WidgetsBindingObserver {
  late final QrCamera _camera = widget.camera();
  StreamSubscription<String>? _codes;
  Timer? _timer;
  _State _state = _State.starting;
  bool _done = false;
  bool _paused = false;
  bool _torch = false;
  String? _invalid;
  Timer? _invalidTimer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _codes = _camera.codes.listen(_onCode);
    // The preview must be in the tree before the camera starts.
    WidgetsBinding.instance.addPostFrameCallback((_) => _start());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _timer?.cancel();
    _invalidTimer?.cancel();
    _codes?.cancel();
    _camera.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (_done) return;
    switch (state) {
      case AppLifecycleState.inactive:
      case AppLifecycleState.hidden:
      case AppLifecycleState.paused:
        // Only a RUNNING camera is released. While starting, the system
        // permission dialog itself makes the app inactive: reacting to it
        // would ask the permission again in a loop (seen on Android 10).
        if (!_paused && _state == _State.scanning) {
          _paused = true;
          _timer?.cancel();
          _camera.stop();
        }
      case AppLifecycleState.resumed:
        // Back from the background: start again; a permission revoked
        // meanwhile is reported by the camera (refused panel). A refused
        // camera is only asked again from the panel, by the user.
        if (_paused) {
          _paused = false;
          _start();
        }
      case AppLifecycleState.detached:
        break;
    }
  }

  Future<void> _start() async {
    if (!mounted || _done) return;
    setState(() => _state = _State.starting);
    try {
      await _camera.start();
    } on QrCameraException catch (error) {
      if (!mounted) return;
      setState(
        () => _state = switch (error.failure) {
          QrCameraFailure.permissionDenied => _State.denied,
          QrCameraFailure.unavailable => _State.unavailable,
          QrCameraFailure.other => _State.failed,
        },
      );
      return;
    }
    if (!mounted || _done) return;
    setState(() => _state = _State.scanning);
    _timer?.cancel();
    _timer = Timer(widget.timeout, _timedOut);
  }

  void _timedOut() {
    if (!mounted || _done || _state != _State.scanning) return;
    _camera.stop();
    setState(() => _state = _State.timedOut);
  }

  void _onCode(String raw) {
    if (_done || _state != _State.scanning) return;
    final value = raw.trim();
    if (!looksLikeQrToken(value)) {
      if (_invalid == null) {
        setState(() => _invalid = 'Ce QR n\'est pas une carte d\'élève : il n\'est pas envoyé.');
        _invalidTimer?.cancel();
        _invalidTimer = Timer(const Duration(seconds: 3), () {
          if (mounted) setState(() => _invalid = null);
        });
      }
      return;
    }
    // First valid card: lock, feedback, release the camera, close.
    _done = true;
    _timer?.cancel();
    HapticFeedback.mediumImpact();
    _camera.stop();
    Navigator.of(context).pop(value);
  }

  Future<void> _toggleTorch() async {
    await _camera.toggleTorch();
    if (mounted) setState(() => _torch = !_torch);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        title: const Text('Scanner une carte'),
        actions: [
          if (_state == _State.scanning)
            IconButton(
              key: const Key('camera.torch'),
              tooltip: _torch ? 'Éteindre la lampe' : 'Allumer la lampe (faible luminosité)',
              onPressed: _toggleTorch,
              icon: Icon(_torch ? Icons.flash_on : Icons.flash_off),
            ),
        ],
      ),
      body: Stack(
        fit: StackFit.expand,
        children: [
          _camera.preview(context),
          if (_state == _State.scanning || _state == _State.starting) const _Frame(),
          if (_state == _State.starting) const Center(child: CircularProgressIndicator(color: Colors.white)),
          if (_state == _State.scanning)
            const Positioned(
              left: 24,
              right: 24,
              bottom: 32,
              child: Text(
                'Placez le QR de la carte dans le cadre',
                key: Key('camera.hint'),
                textAlign: TextAlign.center,
                style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w600),
              ),
            ),
          if (_invalid != null)
            Positioned(left: 16, right: 16, top: 16, child: MessageBanner(_invalid!, key: const Key('camera.invalid'))),
          ?_panel(),
        ],
      ),
    );
  }

  Widget? _panel() {
    final (String title, String text, IconData icon) = switch (_state) {
      _State.denied => (
        'Accès à l\'appareil photo refusé',
        'L\'application a besoin de l\'appareil photo pour lire la carte. Aucune photo n\'est enregistrée ni envoyée : '
            'seul le code du QR est transmis. Autorisez l\'appareil photo, ou utilisez la saisie manuelle.',
        Icons.no_photography_outlined,
      ),
      _State.unavailable => (
        'Appareil photo indisponible',
        'Aucun appareil photo utilisable (absent ou occupé par une autre application). Utilisez la saisie manuelle '
            'ou un lecteur QR.',
        Icons.videocam_off_outlined,
      ),
      _State.failed => (
        'L\'appareil photo ne démarre pas',
        'Réessayez ; si le problème persiste, utilisez la saisie manuelle.',
        Icons.error_outline,
      ),
      _State.timedOut => (
        'Aucune carte détectée',
        'L\'appareil photo a été arrêté pour économiser la batterie.',
        Icons.timer_off_outlined,
      ),
      _ => ('', '', Icons.info),
    };
    if (title.isEmpty) return null;
    return ColoredBox(
      color: Tokens.surface,
      child: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const SizedBox(height: 16),
              Icon(icon, size: 52, color: Tokens.primary),
              const SizedBox(height: 12),
              Text(
                title,
                key: const Key('camera.panel'),
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 10),
              Text(text, textAlign: TextAlign.center),
              const SizedBox(height: 20),
              if (_state != _State.unavailable)
                FilledButton.icon(
                  key: const Key('camera.retry'),
                  onPressed: _start,
                  icon: const Icon(Icons.refresh),
                  label: Text(_state == _State.denied ? 'Autoriser l\'appareil photo' : 'Réessayer'),
                ),
              if (_state == _State.denied) ...[
                const SizedBox(height: 8),
                OutlinedButton.icon(
                  key: const Key('camera.settings'),
                  onPressed: openAppSettings,
                  icon: const Icon(Icons.settings_outlined),
                  label: const Text('Ouvrir les paramètres'),
                ),
              ],
              const SizedBox(height: 8),
              TextButton(
                key: const Key('camera.manual'),
                onPressed: () => Navigator.of(context).pop(),
                child: const Text('Saisie manuelle / lecteur QR'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Viewfinder: a square in the middle, whatever the size or orientation.
class _Frame extends StatelessWidget {
  const _Frame();

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final side = constraints.biggest.shortestSide * 0.7;
      return Center(
        child: Container(
          width: side,
          height: side,
          decoration: BoxDecoration(
            border: Border.all(color: Colors.white, width: 3),
            borderRadius: BorderRadius.circular(16),
          ),
        ),
      );
    },
  );
}
