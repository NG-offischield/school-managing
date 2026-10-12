/// Server chosen at runtime, for the four apps.
///
/// [ServerHost] sits at the root. For the current server it builds the
/// app's WHOLE client graph through [ServerSession] (API client, session,
/// repositories, live connection), under a key of its own. Switching server:
///   1. the old session is left ([ServerSession.leave]: server logout if it
///      still answers, refresh token deleted, local caches of the old school
///      cleared);
///   2. the new address is saved;
///   3. a NEW graph is built for it — the old widgets, their data and their
///      WebSocket are disposed with the old key: two schools never mix.
/// The settings screen tests the real health endpoint before saving, and the
/// change is always confirmed. Nothing here decides a permission: the server
/// still does.
library;

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../config/app_config.dart';
import '../config/local_network.dart';
import '../config/server_endpoint.dart';
import '../theme/app_theme.dart';
import '../widgets/widgets.dart';

/// Everything an app builds for ONE server.
class ServerSession {
  const ServerSession({required this.app, this.onReady, required this.leave});

  final Widget app;

  /// Once Android lets the app reach the server (e.g. restore the session).
  final VoidCallback? onReady;

  /// Called before switching away from this server: close the session and
  /// clear what belongs to the old school (tokens, cached documents).
  final Future<void> Function() leave;
}

typedef SessionFactory = ServerSession Function(AppConfig config);

abstract class ServerControl {
  AppConfig? get current;
  ServerSource get source;
  AppConfig? get buildConfig;

  /// Why a saved or built-in address was not used.
  String? get warning;

  /// Real check of [config] (local network permission on Android 17, then GET health/).
  Future<ServerCheck> check(AppConfig config);

  /// Switch to [config] (saved). Same address as now: nothing happens.
  Future<void> use(AppConfig config);

  /// Forget the saved address and go back to the build's own.
  Future<void> useBuild();
}

/// Gives the screens (sign-in, profile) access to the [ServerControl].
class ServerScope extends InheritedWidget {
  const ServerScope({super.key, required this.control, required super.child});

  final ServerControl control;

  static ServerControl? maybeOf(BuildContext context) => context.getInheritedWidgetOfExactType<ServerScope>()?.control;

  @override
  bool updateShouldNotify(ServerScope oldWidget) => control != oldWidget.control;
}

class ServerHost extends StatefulWidget {
  const ServerHost({
    super.key,
    required this.store,
    required this.session,
    this.buildApiUrl = '',
    this.buildWsUrl = '',
    this.access = const LocalNetworkAccess(),
    this.httpClient,
    this.release,
  });

  /// Where the user's choice is kept (one per app).
  final EndpointStore store;
  final SessionFactory session;

  /// The build's `--dart-define`s (initial value, priority 2).
  final String buildApiUrl;
  final String buildWsUrl;
  final LocalNetworkAccess access;

  /// Tests: the health check's HTTP client.
  final http.Client? httpClient;

  /// Tests: force debug/release rules (null = this build's).
  final bool? release;

  @override
  State<ServerHost> createState() => _ServerHostState();
}

class _ServerHostState extends State<ServerHost> implements ServerControl {
  ServerResolution? _resolution;
  ServerSession? _session;
  int _generation = 0;

  @override
  AppConfig? get current => _resolution?.config;

  @override
  ServerSource get source => _resolution?.source ?? ServerSource.none;

  @override
  AppConfig? get buildConfig => _resolution?.build;

  @override
  String? get warning => _resolution?.warning;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final saved = await widget.store.read();
    if (!mounted) return;
    _apply(
      resolveServer(
        saved: saved,
        buildApiUrl: widget.buildApiUrl,
        buildWsUrl: widget.buildWsUrl,
        release: widget.release,
      ),
    );
  }

  void _apply(ServerResolution resolution) {
    final config = resolution.config;
    setState(() {
      _resolution = resolution;
      _generation++;
      _session = config == null ? null : widget.session(config);
    });
  }

  @override
  Future<ServerCheck> check(AppConfig config) async {
    if (needsLocalNetwork(config)) {
      var status = await widget.access.status();
      if (status.blocked && status.canAsk) status = await widget.access.request();
      if (status.blocked) {
        return const ServerCheck(
          ServerCheckKind.localNetworkDenied,
          'Android refuse l\'accès au réseau local : autorisez « Appareils à proximité » pour cette application.',
        );
      }
    }
    return checkServer(config, client: widget.httpClient);
  }

  @override
  Future<void> use(AppConfig config) async {
    if (source == ServerSource.saved && current?.serverAddress == config.serverAddress) return;
    await _session?.leave();
    await widget.store.write(config.serverAddress);
    if (!mounted) return;
    _apply(ServerResolution(config, ServerSource.saved, build: buildConfig));
  }

  @override
  Future<void> useBuild() async {
    final build = buildConfig;
    if (build == null) return;
    await _session?.leave();
    await widget.store.clear();
    if (!mounted) return;
    _apply(ServerResolution(build, ServerSource.build, build: build));
  }

  @override
  Widget build(BuildContext context) {
    final resolution = _resolution;
    if (resolution == null) {
      return ColoredBox(
        color: Tokens.navy,
        child: Center(child: CircularProgressIndicator(color: Colors.white)),
      );
    }
    final config = resolution.config;
    final session = _session;
    final Widget child = config == null || session == null
        // Priority 3: no address at all — the user types the server's.
        ? MaterialApp(
            debugShowCheckedModeBanner: false,
            theme: buildAppTheme(),
            darkTheme: buildAppTheme(brightness: Brightness.dark),
            themeMode: themeModeOf(context),
            builder: themedScreens,
            home: ServerSettingsScreen(control: this, firstRun: true),
          )
        : LocalNetworkGate(config: config, onReady: session.onReady, access: widget.access, child: session.app);
    return ServerScope(
      control: this,
      child: KeyedSubtree(key: ValueKey(_generation), child: child),
    );
  }
}

/// Opens the server settings above the current screen (sign-in, profile).
Future<void> openServerSettings(BuildContext context, ServerControl control) =>
    Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => ServerSettingsScreen(control: control)));

class ServerSettingsScreen extends StatefulWidget {
  const ServerSettingsScreen({super.key, required this.control, this.firstRun = false});

  final ServerControl control;
  final bool firstRun;

  @override
  State<ServerSettingsScreen> createState() => _ServerSettingsScreenState();
}

class _ServerSettingsScreenState extends State<ServerSettingsScreen> {
  late final _address = TextEditingController(text: widget.control.current?.serverAddress ?? '');
  ServerCheck? _result;
  String? _checkedAddress; // the address the result is about
  bool _busy = false;

  @override
  void dispose() {
    _address.dispose();
    super.dispose();
  }

  AppConfig? _parse() {
    try {
      return AppConfig.server(_address.text);
    } on AppConfigException catch (error) {
      setState(() {
        _result = ServerCheck(ServerCheckKind.invalidAddress, error.message);
        _checkedAddress = null;
      });
      return null;
    }
  }

  Future<void> _test() async {
    final config = _parse();
    if (config == null) return;
    setState(() => _busy = true);
    final result = await widget.control.check(config);
    if (!mounted) return;
    setState(() {
      _busy = false;
      _result = result;
      _checkedAddress = config.serverAddress;
    });
  }

  Future<void> _save() async {
    final config = _parse();
    if (config == null) return;
    final control = widget.control;
    if (control.current?.serverAddress == config.serverAddress) {
      Navigator.of(context).maybePop(); // unchanged: same session, nothing cleared
      return;
    }
    final verified = _checkedAddress == config.serverAddress && (_result?.ok ?? false);
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Changer de serveur ?'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Nouveau serveur : ${config.serverAddress}', key: const Key('server.confirm.address')),
            const SizedBox(height: 10),
            const Text(
              'Vous serez déconnecté(e). La session et les documents enregistrés pour l\'ancien serveur '
              'seront effacés de ce téléphone.',
            ),
            if (!verified) ...[
              const SizedBox(height: 10),
              Text(
                'La connexion à ce serveur n\'a pas été vérifiée.',
                style: TextStyle(color: Tokens.warning, fontWeight: FontWeight.w600),
              ),
            ],
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Annuler')),
          FilledButton(
            key: const Key('server.confirm.ok'),
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Changer'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => _busy = true);
    await control.use(config); // rebuilds the app for the new server (this screen goes with the old one)
  }

  Future<void> _backToBuild() async {
    setState(() => _busy = true);
    await widget.control.useBuild();
  }

  @override
  Widget build(BuildContext context) {
    final control = widget.control;
    final current = control.current;
    final result = _result;
    final clearText = _address.text.trim().isNotEmpty && !_address.text.trim().startsWith('https://');
    return Scaffold(
      appBar: AppBar(title: const Text('Serveur de l\'établissement'), automaticallyImplyLeading: !widget.firstRun),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Text(
            current == null
                ? 'Aucun serveur configuré.'
                : 'Serveur actuel : ${current.serverAddress}'
                      '${control.source == ServerSource.build ? ' (adresse d\'installation)' : ' (enregistré sur ce téléphone)'}',
            key: const Key('server.current'),
            style: const TextStyle(fontWeight: FontWeight.w600),
          ),
          if (control.warning != null) ...[const SizedBox(height: 10), MessageBanner(control.warning!)],
          const SizedBox(height: 16),
          TextField(
            key: const Key('server.address'),
            controller: _address,
            keyboardType: TextInputType.url,
            autocorrect: false,
            onChanged: (_) => setState(() => _result = null),
            decoration: const InputDecoration(
              labelText: 'Adresse du serveur',
              hintText: 'http://<IPv4 du PC>:8000',
              helperText: 'Affichée par configure_lan.ps1 sur le PC du serveur.',
            ),
          ),
          if (clearText) ...[
            const SizedBox(height: 8),
            Text(
              'HTTP non chiffré : réservé au réseau local de confiance de l\'établissement, '
              'jamais pour un serveur exposé sur Internet.',
              style: TextStyle(color: Tokens.textSecondary, fontSize: 12),
            ),
          ],
          const SizedBox(height: 16),
          OutlinedButton.icon(
            key: const Key('server.test'),
            onPressed: _busy ? null : _test,
            icon: const Icon(Icons.network_check),
            label: const Text('Tester la connexion'),
          ),
          if (_busy) ...[const SizedBox(height: 12), const LinearProgressIndicator()],
          if (result != null) ...[
            const SizedBox(height: 12),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(
                  result.ok ? Icons.check_circle : Icons.error_outline,
                  color: result.ok ? Tokens.success : Tokens.error,
                ),
                const SizedBox(width: 8),
                Expanded(child: Text(result.message, key: const Key('server.result'))),
              ],
            ),
          ],
          const SizedBox(height: 20),
          FilledButton.icon(
            key: const Key('server.save'),
            onPressed: _busy ? null : _save,
            icon: const Icon(Icons.save_outlined),
            label: const Text('Enregistrer'),
          ),
          if (control.source == ServerSource.saved && control.buildConfig != null) ...[
            const SizedBox(height: 8),
            TextButton(
              key: const Key('server.reset'),
              onPressed: _busy ? null : _backToBuild,
              child: Text('Revenir à l\'adresse d\'installation (${control.buildConfig!.serverAddress})'),
            ),
          ],
        ],
      ),
    );
  }
}

/// « Serveur » entry for a profile / settings screen (hidden outside a [ServerHost]).
class ServerSettingsTile extends StatelessWidget {
  const ServerSettingsTile({super.key});

  @override
  Widget build(BuildContext context) {
    final control = ServerScope.maybeOf(context);
    final current = control?.current;
    if (control == null || current == null) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Card(
        child: ListTile(
          key: const Key('profile.server'),
          leading: const Icon(Icons.dns_outlined),
          title: const Text('Serveur'),
          subtitle: Text(current.serverAddress),
          trailing: const Icon(Icons.chevron_right),
          onTap: () => openServerSettings(context, control),
        ),
      ),
    );
  }
}
