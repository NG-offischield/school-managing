/// Android 17 local network protection, for the four apps.
///
/// Apps targeting API 37 need the runtime permission ACCESS_LOCAL_NETWORK to
/// reach a PRIVATE address (the PC running Django on the school's Wi-Fi):
/// without it, connections just time out. The native side
/// (android/…/SchoolCorePlugin.kt) only asks on API 37+; on Android 10–16
/// INTERNET is enough and nothing is shown.
///
/// [LocalNetworkGate] sits above the app: when the API address is on the
/// LAN and the permission is missing it explains why, asks, handles a
/// refusal (ask again / app settings) and re-checks when the app comes back
/// to the foreground (the permission can be revoked from the settings).
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../theme/app_theme.dart';
import '../widgets/widgets.dart';
import 'app_config.dart';
import '../l10n/l10n.dart';

class LocalNetworkStatus {
  const LocalNetworkStatus({required this.required, required this.granted, this.canAsk = false, this.sdkInt});

  /// Not Android / API < 37: nothing to ask.
  static const notRequired = LocalNetworkStatus(required: false, granted: true);

  factory LocalNetworkStatus.fromMap(Map<Object?, Object?> map) => LocalNetworkStatus(
    required: map['required'] == true,
    granted: map['granted'] == true,
    canAsk: map['canAsk'] == true,
    sdkInt: map['sdkInt'] as int?,
  );

  final bool required;
  final bool granted;

  /// false + not granted: refused for good, only the app settings can grant it.
  final bool canAsk;
  final int? sdkInt;

  bool get blocked => required && !granted;
}

/// The platform channel (overridable in tests).
class LocalNetworkAccess {
  const LocalNetworkAccess([this._channel = const MethodChannel('school_core/local_network')]);

  final MethodChannel _channel;

  Future<LocalNetworkStatus> status() => _call('status');

  Future<LocalNetworkStatus> request() => _call('request');

  Future<void> openSettings() async {
    try {
      await _channel.invokeMethod<bool>('openSettings');
    } on MissingPluginException {
      // not Android
    }
  }

  Future<LocalNetworkStatus> _call(String method) async {
    try {
      final map = await _channel.invokeMethod<Map<Object?, Object?>>(method);
      return map == null ? LocalNetworkStatus.notRequired : LocalNetworkStatus.fromMap(map);
    } on MissingPluginException {
      return LocalNetworkStatus.notRequired; // desktop, tests: no Android rule
    }
  }
}

/// Does reaching [config] need the local network permission? Only a private
/// address does; loopback (`adb reverse`) does not.
bool needsLocalNetwork(AppConfig config) {
  final host = config.api.host;
  return isPrivateHost(host) && host != 'localhost' && !host.startsWith('127.');
}

class LocalNetworkGate extends StatefulWidget {
  const LocalNetworkGate({
    super.key,
    required this.config,
    required this.child,
    this.onReady,
    this.access = const LocalNetworkAccess(),
  });

  final AppConfig config;
  final Widget child;

  /// Called once, when Android lets the app reach the backend (e.g. restore
  /// the session: no request goes out before).
  final VoidCallback? onReady;
  final LocalNetworkAccess access;

  @override
  State<LocalNetworkGate> createState() => _LocalNetworkGateState();
}

class _LocalNetworkGateState extends State<LocalNetworkGate> with WidgetsBindingObserver {
  LocalNetworkStatus? _status;
  bool _ready = false;
  bool _asking = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _check(ask: true);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Back from the settings (granted there), or revoked meanwhile.
    if (state == AppLifecycleState.resumed && !_asking) _check(ask: false);
  }

  Future<void> _check({required bool ask}) async {
    if (!needsLocalNetwork(widget.config)) return _set(LocalNetworkStatus.notRequired);
    var status = await widget.access.status();
    if (status.blocked && ask && status.canAsk) status = await _request();
    _set(status);
  }

  Future<LocalNetworkStatus> _request() async {
    _asking = true;
    try {
      return await widget.access.request();
    } finally {
      _asking = false;
    }
  }

  void _set(LocalNetworkStatus status) {
    if (!mounted) return;
    setState(() => _status = status);
    if (!status.blocked && !_ready) {
      _ready = true;
      widget.onReady?.call();
    }
  }

  @override
  Widget build(BuildContext context) {
    final status = _status;
    if (status == null) {
      return ColoredBox(
        color: Tokens.navy,
        child: Center(child: CircularProgressIndicator(color: Colors.white)),
      );
    }
    if (!status.blocked) return widget.child;
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: buildAppTheme(),
      home: _PermissionScreen(
        server: widget.config.serverLabel,
        canAsk: status.canAsk,
        onAsk: () async => _set(await _request()),
        onSettings: widget.access.openSettings,
      ),
    );
  }
}

class _PermissionScreen extends StatelessWidget {
  const _PermissionScreen({required this.server, required this.canAsk, required this.onAsk, required this.onSettings});

  final String server;
  final bool canAsk;
  final VoidCallback onAsk;
  final VoidCallback onSettings;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const SizedBox(height: 24),
              Icon(Icons.wifi_tethering, size: 56, color: Tokens.primary),
              const SizedBox(height: 16),
              Text(
                tr('Accès au réseau local'),
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 12),
              Text(
                tr(
                  'Le serveur de l\'établissement ({0}) se trouve sur le réseau Wi-Fi local. Android demande votre accord pour que l\'application puisse le joindre : sans cet accès, la connexion, les messages et les notifications ne fonctionnent pas.',
                  [server],
                ),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 20),
              if (!canAsk) ...[
                MessageBanner(
                  tr(
                    'L\'accès a été refusé. Autorisez « Appareils à proximité » (réseau local) dans les paramètres de l\'application, puis revenez ici.',
                  ),
                ),
                const SizedBox(height: 16),
                FilledButton.icon(
                  key: const Key('lan.settings'),
                  onPressed: onSettings,
                  icon: const Icon(Icons.settings_outlined),
                  label: Text(tr('Ouvrir les paramètres')),
                ),
              ] else
                FilledButton.icon(
                  key: const Key('lan.ask'),
                  onPressed: onAsk,
                  icon: const Icon(Icons.check),
                  label: Text(tr('Autoriser l\'accès au réseau local')),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Shown instead of the app when API_URL / WS_URL are missing or refused.
class ConfigErrorApp extends StatelessWidget {
  const ConfigErrorApp(this.message, {super.key});

  final String message;

  @override
  Widget build(BuildContext context) => MaterialApp(
    debugShowCheckedModeBanner: false,
    theme: buildAppTheme(),
    home: Scaffold(
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const SizedBox(height: 24),
              Icon(Icons.dns_outlined, size: 56, color: Tokens.error),
              const SizedBox(height: 16),
              Text(
                tr('Configuration du serveur'),
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 16),
              MessageBanner(message),
            ],
          ),
        ),
      ),
    ),
  );
}

/// Opens this app's page in the Android settings (a permission refused for
/// good: local network, camera...). Same native channel; no-op elsewhere.
Future<void> openAppSettings() => const LocalNetworkAccess().openSettings();

/// Shows a downloaded document (official PDF) with the phone's viewer.
/// False when there is no viewer or no Android side: the file stays saved.
Future<bool> openDocument(String path, {String mimeType = 'application/pdf'}) async {
  try {
    return await const MethodChannel(
          'school_core/local_network',
        ).invokeMethod<bool>('openDocument', {'path': path, 'mimeType': mimeType}) ??
        false;
  } on MissingPluginException {
    return false;
  }
}

/// Server switch: deletes the copies of documents handed to the phone's
/// viewers (cache/shared/). False without an Android side (nothing to delete).
Future<bool> clearSharedDocuments() async {
  try {
    return await const MethodChannel('school_core/local_network').invokeMethod<bool>('clearSharedDocuments') ?? false;
  } on MissingPluginException {
    return false;
  }
}

/// An image the user chose with the system picker: its bytes, or why it
/// could not be read ([error]: `too_large` above 3 MB, `unreadable`).
class PickedImage {
  const PickedImage({this.bytes, this.error});

  final Uint8List? bytes;
  final String? error;
}

/// System photo picker (Android Photo Picker / ACTION_GET_CONTENT): no storage
/// permission. Null when cancelled or without an Android side.
Future<PickedImage?> pickImage() async {
  try {
    final result = await const MethodChannel('school_core/local_network').invokeMapMethod<String, Object?>('pickImage');
    if (result == null) return null;
    final bytes = result['bytes'];
    return PickedImage(bytes: bytes is Uint8List ? bytes : null, error: result['error'] as String?);
  } on MissingPluginException {
    return null;
  }
}
