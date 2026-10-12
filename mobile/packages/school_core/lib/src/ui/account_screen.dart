import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/api_error.dart';
import '../auth/auth_service.dart';
import '../config/local_network.dart';
import '../data/account.dart';
import '../theme/app_theme.dart';
import '../widgets/widgets.dart';
import 'live_state.dart';
import '../l10n/l10n.dart';

/// Chooses an image (system picker on a phone; injectable in tests).
typedef ImageChooser = Future<PickedImage?> Function();

/// « Mon compte et paramètres », shared by the four apps: photo, the contact
/// details the SERVER lets this member change, password, sessions. Identity,
/// login, role and school are shown, never editable here.
class AccountScreen extends StatefulWidget {
  const AccountScreen({super.key, this.chooseImage = pickImage, this.extra = const []});

  final ImageChooser chooseImage;

  /// App-specific sections (e.g. the theme choice), shown before « Sécurité ».
  final List<Widget> extra;

  @override
  State<AccountScreen> createState() => _AccountScreenState();
}

class _AccountScreenState extends State<AccountScreen> {
  late final AccountRepository _repo = AccountRepository(context.read<AuthService>().api);
  Future<AccountProfile>? _future;
  Uint8List? _photo;
  final _fields = <String, TextEditingController>{};
  String? _language;
  Map<String, List<String>> _errors = const {};
  String? _message;
  Tone _tone = Tone.success;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    for (final c in _fields.values) {
      c.dispose();
    }
    super.dispose();
  }

  void _load() {
    final future = _repo.profile().then((profile) async {
      _fill(profile);
      final photo = profile.hasPhoto ? await _repo.photo() : null;
      if (mounted) setState(() => _photo = photo);
      return profile;
    });
    setState(() {
      _future = future;
    });
  }

  void _fill(AccountProfile profile) {
    for (final field in profile.editable) {
      if (field == 'preferred_language') {
        _language = profile.values[field];
        continue;
      }
      (_fields[field] ??= TextEditingController()).text = profile.values[field] ?? '';
    }
  }

  void _say(String text, Tone tone) => setState(() {
    _message = text;
    _tone = tone;
  });

  Future<void> _save(AccountProfile profile) async {
    final changes = <String, String>{};
    _fields.forEach((field, controller) {
      if (controller.text.trim() != (profile.values[field] ?? '')) changes[field] = controller.text.trim();
    });
    if (_language != null && _language != profile.values['preferred_language']) {
      changes['preferred_language'] = _language!;
    }
    if (changes.isEmpty) {
      _say(tr('Aucune modification à enregistrer.'), Tone.info);
      return;
    }
    setState(() {
      _busy = true;
      _errors = const {};
    });
    try {
      final saved = await _repo.update(changes);
      _fill(saved);
      setState(() {
        _future = Future.value(saved);
      });
      _say(tr('Coordonnées enregistrées.'), Tone.success);
    } on ApiException catch (error) {
      setState(() => _errors = error.fieldErrors);
      _say(error.fieldErrors.isEmpty ? error.userMessage : tr('Vérifiez les champs signalés.'), Tone.danger);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _changePhoto() async {
    final picked = await widget.chooseImage();
    if (picked == null || !mounted) return;
    if (picked.bytes == null) {
      _say(
        picked.error == 'too_large'
            ? tr('Cette image dépasse 3 Mo : choisissez-en une plus légère.')
            : tr('Cette image n\'a pas pu être lue.'),
        Tone.danger,
      );
      return;
    }
    setState(() => _busy = true);
    try {
      final saved = await _repo.uploadPhoto(picked.bytes!);
      final photo = await _repo.photo();
      setState(() {
        _future = Future.value(saved);
        _photo = photo;
      });
      _say(tr('Photo mise à jour.'), Tone.success);
    } on ApiException catch (error) {
      _say(_photoMessage(error), Tone.danger);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String _photoMessage(ApiException error) => switch (error.rule) {
    'photo_invalid' => tr('Ce fichier n\'est pas une image lisible.'),
    'photo_format' => tr('Utilisez une photo JPEG, PNG ou WebP.'),
    'photo_too_small' => tr('La photo est trop petite (120 px minimum de côté).'),
    'photo_too_large' => tr('La photo est trop grande (3 Mo maximum).'),
    _ => error.userMessage,
  };

  Future<void> _removePhoto() async {
    setState(() => _busy = true);
    try {
      final saved = await _repo.deletePhoto();
      setState(() {
        _future = Future.value(saved);
        _photo = null;
      });
      _say(tr('Photo retirée.'), Tone.success);
    } on ApiException catch (error) {
      _say(error.userMessage, Tone.danger);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr('Mon compte'))),
      body: AsyncBody<AccountProfile>(
        future: _future,
        onRetry: _load,
        builder: (context, profile) => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            _identity(profile),
            if (_message != null)
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: MessageBanner(_message!, tone: _tone),
              ),
            const SizedBox(height: 12),
            _details(profile),
            const ThemeChoice(),
            const LanguageChoice(),
            ...widget.extra,
            const SizedBox(height: 12),
            _security(),
          ],
        ),
      ),
    );
  }

  Widget _identity(AccountProfile profile) {
    final initials = [
      profile.firstName,
      profile.lastName,
    ].where((p) => p.isNotEmpty).map((p) => p[0].toUpperCase()).join();
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            CircleAvatar(
              key: const Key('account.avatar'),
              radius: 40,
              backgroundColor: Tokens.primary,
              foregroundImage: _photo == null ? null : MemoryImage(_photo!),
              child: Text(
                initials,
                style: TextStyle(color: Tokens.onPrimary, fontSize: 24, fontWeight: FontWeight.w700),
              ),
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              alignment: WrapAlignment.center,
              children: [
                TextButton.icon(
                  key: const Key('account.photo.change'),
                  onPressed: _busy ? null : _changePhoto,
                  icon: const Icon(Icons.photo_camera_outlined),
                  label: Text(profile.hasPhoto ? tr('Changer la photo') : tr('Ajouter une photo')),
                ),
                if (profile.hasPhoto)
                  TextButton.icon(
                    key: const Key('account.photo.remove'),
                    onPressed: _busy ? null : _removePhoto,
                    icon: const Icon(Icons.delete_outline),
                    label: Text(tr('Retirer')),
                  ),
              ],
            ),
            Text(profile.fullName, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
            Text(profile.email, style: TextStyle(color: Tokens.textSecondary)),
            const SizedBox(height: 6),
            Text('${profile.rolesLabel} · ${profile.schoolName}', textAlign: TextAlign.center),
            const SizedBox(height: 6),
            Text(
              tr(
                'Le nom, l\'adresse e-mail, le rôle et l\'établissement sont gérés par l\'administration de l\'école.',
              ),
              textAlign: TextAlign.center,
              style: TextStyle(color: Tokens.textSecondary, fontSize: 12.5),
            ),
          ],
        ),
      ),
    );
  }

  Widget _details(AccountProfile profile) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(tr('Mes coordonnées'), style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
            const SizedBox(height: 8),
            for (final field in profile.editable)
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: field == 'preferred_language'
                    ? DropdownButtonFormField<String>(
                        key: const Key('account.field.preferred_language'),
                        initialValue: profile.languages.containsKey(_language) ? _language : null,
                        decoration: InputDecoration(
                          labelText: accountFieldLabels[field],
                          errorText: _errors[field]?.join(' '),
                        ),
                        items: [
                          for (final entry in profile.languages.entries)
                            DropdownMenuItem(value: entry.key, child: Text(entry.value)),
                        ],
                        onChanged: _busy ? null : (value) => setState(() => _language = value),
                      )
                    : TextField(
                        key: Key('account.field.$field'),
                        controller: _fields[field],
                        enabled: !_busy,
                        maxLines: field == 'address' ? 3 : 1,
                        minLines: 1,
                        keyboardType: field.contains('phone') ? TextInputType.phone : TextInputType.text,
                        decoration: InputDecoration(
                          labelText: accountFieldLabels[field] ?? field,
                          errorText: _errors[field]?.join(' '),
                        ),
                      ),
              ),
            FilledButton.icon(
              key: const Key('account.save'),
              onPressed: _busy ? null : () => _save(profile),
              icon: const Icon(Icons.save_outlined),
              label: Text(tr('Enregistrer')),
            ),
          ],
        ),
      ),
    );
  }

  Widget _security() {
    return Card(
      child: Column(
        children: [
          ListTile(
            key: const Key('account.password'),
            leading: const Icon(Icons.lock_outline),
            title: Text(tr('Changer mon mot de passe')),
            subtitle: Text(tr('Vos autres appareils seront déconnectés.')),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.of(
              context,
            ).push(MaterialPageRoute<void>(builder: (_) => ChangePasswordScreen(repository: _repo))),
          ),
          ListTile(
            key: const Key('account.sessions'),
            leading: const Icon(Icons.devices_outlined),
            title: Text(tr('Mes appareils connectés')),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => ChangeNotifierProvider<AuthService>.value(
                  value: context.read<AuthService>(),
                  child: SessionsScreen(repository: _repo),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class ChangePasswordScreen extends StatefulWidget {
  const ChangePasswordScreen({super.key, required this.repository});

  final AccountRepository repository;

  @override
  State<ChangePasswordScreen> createState() => _ChangePasswordScreenState();
}

class _ChangePasswordScreenState extends State<ChangePasswordScreen> {
  final _current = TextEditingController();
  final _next = TextEditingController();
  final _confirm = TextEditingController();
  Map<String, List<String>> _errors = const {};
  String? _error;
  bool _busy = false;
  bool _done = false;
  bool _visible = false; // passwords shown in clear while the user checks them

  Widget _eye() => IconButton(
    key: const Key('password.visibility'),
    tooltip: _visible ? tr('Masquer le mot de passe') : tr('Afficher le mot de passe'),
    icon: Icon(_visible ? Icons.visibility_off_outlined : Icons.visibility_outlined),
    onPressed: () => setState(() => _visible = !_visible),
  );

  @override
  void dispose() {
    _current.dispose();
    _next.dispose();
    _confirm.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_current.text.isEmpty || _next.text.isEmpty) {
      setState(() => _error = tr('Saisissez le mot de passe actuel et le nouveau.'));
      return;
    }
    if (_next.text != _confirm.text) {
      setState(() => _error = tr('La confirmation ne correspond pas au nouveau mot de passe.'));
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
      _errors = const {};
    });
    try {
      await widget.repository.changePassword(_current.text, _next.text);
      setState(() => _done = true);
    } on ApiException catch (error) {
      setState(() {
        _errors = error.fieldErrors;
        _error = error.fieldErrors.isEmpty ? error.userMessage : null;
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr('Mot de passe'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_done) ...[
            MessageBanner(
              tr('Mot de passe changé. Vos autres appareils ont été déconnectés ; celui-ci reste connecté.'),
              tone: Tone.success,
            ),
            const SizedBox(height: 16),
            FilledButton(onPressed: () => Navigator.of(context).pop(), child: Text(tr('Terminer'))),
          ] else ...[
            if (_error != null) ...[MessageBanner(_error!), const SizedBox(height: 12)],
            TextField(
              key: const Key('password.current'),
              controller: _current,
              obscureText: !_visible,
              enabled: !_busy,
              decoration: InputDecoration(
                labelText: tr('Mot de passe actuel'),
                suffixIcon: _eye(),
                errorText: _errors['current_password']?.join(' '),
              ),
            ),
            const SizedBox(height: 10),
            TextField(
              key: const Key('password.new'),
              controller: _next,
              obscureText: !_visible,
              enabled: !_busy,
              decoration: InputDecoration(
                labelText: tr('Nouveau mot de passe'),
                suffixIcon: _eye(),
                helperText: tr('10 caractères au minimum, pas trop courant.'),
                errorText: _errors['new_password']?.join(' '),
              ),
            ),
            const SizedBox(height: 10),
            TextField(
              key: const Key('password.confirm'),
              controller: _confirm,
              obscureText: !_visible,
              enabled: !_busy,
              decoration: InputDecoration(labelText: tr('Confirmer le nouveau mot de passe'), suffixIcon: _eye()),
            ),
            const SizedBox(height: 16),
            FilledButton(
              key: const Key('password.submit'),
              onPressed: _busy ? null : _submit,
              child: Text(tr('Changer le mot de passe')),
            ),
          ],
        ],
      ),
    );
  }
}

/// Where I am signed in; any other device can be disconnected.
class SessionsScreen extends StatefulWidget {
  const SessionsScreen({super.key, required this.repository});

  final AccountRepository repository;

  @override
  State<SessionsScreen> createState() => _SessionsScreenState();
}

class _SessionsScreenState extends State<SessionsScreen> {
  Future<List<UserSession>>? _future;
  String? _message;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() {
    final future = widget.repository.sessions();
    setState(() {
      _future = future;
    });
  }

  Future<void> _revoke(UserSession session) async {
    try {
      await widget.repository.revokeSession(session.id);
      _message = tr('« {0} » est déconnecté.', [session.deviceName]);
      _load();
    } on ApiException catch (error) {
      setState(() => _message = error.userMessage);
    }
  }

  Future<void> _revokeAll() async {
    final auth = context.read<AuthService>();
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(tr('Déconnecter tous les appareils ?')),
        content: Text(tr('Tous vos appareils, celui-ci compris, devront se reconnecter.')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: Text(tr('Annuler'))),
          FilledButton(
            key: const Key('sessions.revokeAll.confirm'),
            onPressed: () => Navigator.pop(context, true),
            child: Text(tr('Tout déconnecter')),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await widget.repository.revokeAll();
    } on ApiException {
      // Already revoked or offline: signed out locally anyway.
    }
    if (mounted) Navigator.of(context).popUntil((route) => route.isFirst);
    await auth.logout();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr('Appareils connectés'))),
      body: AsyncBody<List<UserSession>>(
        future: _future,
        onRetry: _load,
        builder: (context, sessions) => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            if (_message != null) ...[MessageBanner(_message!, tone: Tone.info), const SizedBox(height: 12)],
            for (final s in sessions)
              Card(
                child: ListTile(
                  key: Key('session.${s.id}'),
                  leading: Icon(s.platform == 'ANDROID' ? Icons.phone_android : Icons.computer),
                  title: Text(s.deviceName),
                  subtitle: Text(
                    [
                      if (s.current) tr('Cet appareil'),
                      if (s.lastUsedAt != null) tr('actif le {0}', [dateTime.format(s.lastUsedAt!)]),
                    ].join(' · '),
                  ),
                  trailing: s.current
                      ? null
                      : TextButton(
                          key: Key('session.revoke.${s.id}'),
                          onPressed: () => _revoke(s),
                          child: Text(tr('Déconnecter')),
                        ),
                ),
              ),
            const SizedBox(height: 12),
            OutlinedButton.icon(
              key: const Key('sessions.revokeAll'),
              style: OutlinedButton.styleFrom(
                foregroundColor: Tokens.error,
                side: BorderSide(color: Tokens.error),
              ),
              onPressed: _revokeAll,
              icon: const Icon(Icons.logout),
              label: Text(tr('Déconnecter tous mes appareils')),
            ),
          ],
        ),
      ),
    );
  }
}

/// « Apparence »: Système / Clair / Sombre, applied at once and kept on the
/// phone. Nothing is shown when the app provides no [ThemeController].
class ThemeChoice extends StatelessWidget {
  const ThemeChoice({super.key});

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<ThemeController?>();
    if (controller == null) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(tr('Apparence'), style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
              const SizedBox(height: 10),
              SegmentedButton<ThemeMode>(
                key: const Key('account.theme'),
                segments: [
                  for (final entry in themeModeLabels.entries)
                    ButtonSegment(
                      value: entry.key,
                      label: Text(entry.value, key: Key('account.theme.${entry.key.name}')),
                      icon: Icon(switch (entry.key) {
                        ThemeMode.system => Icons.brightness_auto_outlined,
                        ThemeMode.light => Icons.light_mode_outlined,
                        ThemeMode.dark => Icons.dark_mode_outlined,
                      }),
                    ),
                ],
                selected: {controller.mode},
                onSelectionChanged: (choice) => controller.set(choice.single),
              ),
              const SizedBox(height: 6),
              Text(
                tr('« Système » suit le réglage du téléphone.'),
                style: TextStyle(color: Tokens.textSecondary, fontSize: 12.5),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// « Langue »: Français / English, applied at once (open screens included)
/// and kept on the phone. Hidden when the app provides no [LanguageController].
class LanguageChoice extends StatelessWidget {
  const LanguageChoice({super.key});

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<LanguageController?>();
    if (controller == null) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(tr('Langue'), style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
              const SizedBox(height: 10),
              SegmentedButton<AppLanguage>(
                key: const Key('account.language'),
                segments: [
                  for (final language in AppLanguage.values)
                    ButtonSegment(
                      value: language,
                      // Each language is named in its own language.
                      label: Text(language.label, key: Key('account.language.${language.code}')),
                    ),
                ],
                selected: {controller.language},
                onSelectionChanged: (choice) => controller.set(choice.single),
              ),
              const SizedBox(height: 6),
              Text(
                tr('La langue s\'applique tout de suite et reste choisie sur ce téléphone.'),
                style: TextStyle(color: Tokens.textSecondary, fontSize: 12.5),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
