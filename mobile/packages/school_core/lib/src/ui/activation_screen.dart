import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import '../api/api_error.dart';
import '../auth/auth_service.dart';
import '../theme/app_theme.dart';
import '../widgets/widgets.dart';

/// Activation of an account created by the administration (ADR 0024):
///   1. code  -> POST /auth/activation/check/   (who / which school / login)
///   2. password + confirmation -> POST /auth/activation/complete/
///   3. back to the login with the identifier (normal authentication).
/// The code is forgotten as soon as it is used; the password is never kept.
class ActivationScreen extends StatefulWidget {
  const ActivationScreen({super.key});

  @override
  State<ActivationScreen> createState() => _ActivationScreenState();
}

class _ActivationScreenState extends State<ActivationScreen> {
  final _code = TextEditingController();
  final _password = TextEditingController();
  final _confirmation = TextEditingController();
  ActivationPreview? _preview;
  bool _busy = false;
  bool _hidden = true;
  String? _error;
  String? _activatedLogin;

  @override
  void dispose() {
    _code.dispose();
    _password.dispose();
    _confirmation.dispose();
    super.dispose();
  }

  Future<void> _check() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      _preview = await context.read<AuthService>().checkActivation(_code.text);
    } on ApiException catch (error) {
      _error = error.userMessage;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String? get _passwordProblem {
    if (_password.text.isEmpty) return null;
    if (_confirmation.text.isNotEmpty && _confirmation.text != _password.text) {
      return 'Les deux mots de passe ne sont pas identiques.';
    }
    return null;
  }

  bool get _canComplete => !_busy && _password.text.isNotEmpty && _confirmation.text == _password.text;

  Future<void> _complete() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final login = await context.read<AuthService>().completeActivation(_code.text, _password.text);
      _code.clear(); // the code is never shown again
      _activatedLogin = login;
    } on ApiException catch (error) {
      final field = error.fieldErrors['password'];
      _error = field != null ? field.join('\n') : error.userMessage;
      if (error.code == 'INVALID_ACTIVATION_CODE') _preview = null;
    } finally {
      _password.clear();
      _confirmation.clear();
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Activer mon compte')),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 460),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  if (_error != null) ...[MessageBanner(_error!), const SizedBox(height: 16)],
                  if (_activatedLogin != null)
                    ..._done()
                  else if (_preview == null)
                    ..._codeStep()
                  else
                    ..._passwordStep(),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  List<Widget> _codeStep() => [
    const Text(
      'Étape 1 sur 2',
      style: TextStyle(color: Tokens.textSecondary, fontWeight: FontWeight.w600),
    ),
    const SizedBox(height: 6),
    const Text(
      'Saisissez le code d\'activation remis par l\'administration de votre établissement.',
      style: TextStyle(fontSize: 16),
    ),
    const SizedBox(height: 18),
    TextField(
      key: const Key('activation.code'),
      controller: _code,
      textCapitalization: TextCapitalization.characters,
      autocorrect: false,
      enableSuggestions: false,
      style: const TextStyle(fontSize: 18, letterSpacing: 1.5, fontWeight: FontWeight.w600),
      decoration: const InputDecoration(labelText: 'Code d\'activation', hintText: 'XXXX-XXXX-XXXX-XXXX-XXXX'),
      onChanged: (_) => setState(() {}),
      onSubmitted: (_) => _code.text.trim().isEmpty ? null : _check(),
    ),
    const SizedBox(height: 20),
    FilledButton(
      key: const Key('activation.check'),
      onPressed: _busy || _code.text.trim().isEmpty ? null : _check,
      child: const Text('Vérifier le code'),
    ),
  ];

  List<Widget> _passwordStep() {
    final preview = _preview!;
    final expires = preview.expiresAt == null
        ? ''
        : DateFormat('dd/MM/yyyy HH:mm', 'fr_FR').format(preview.expiresAt!.toLocal());
    return [
      const Text(
        'Étape 2 sur 2',
        style: TextStyle(color: Tokens.textSecondary, fontWeight: FontWeight.w600),
      ),
      const SizedBox(height: 6),
      Text('Bonjour ${preview.firstName},', style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
      const SizedBox(height: 6),
      Text(
        'Établissement : ${preview.school}\nIdentifiant : ${preview.login}'
        '${expires.isEmpty ? '' : '\nCode valable jusqu\'au $expires'}',
        style: const TextStyle(fontSize: 15, height: 1.4),
      ),
      const SizedBox(height: 18),
      const Text(
        'Choisissez votre mot de passe : au moins 10 caractères, ni trop courant, ni proche de votre nom.',
        style: TextStyle(color: Tokens.textSecondary),
      ),
      const SizedBox(height: 14),
      TextField(
        key: const Key('activation.password'),
        controller: _password,
        obscureText: _hidden,
        enableSuggestions: false,
        autocorrect: false,
        autofillHints: const [AutofillHints.newPassword],
        onChanged: (_) => setState(() {}),
        decoration: InputDecoration(
          labelText: 'Nouveau mot de passe',
          suffixIcon: IconButton(
            tooltip: _hidden ? 'Afficher' : 'Masquer',
            icon: Icon(_hidden ? Icons.visibility_outlined : Icons.visibility_off_outlined),
            onPressed: () => setState(() => _hidden = !_hidden),
          ),
        ),
      ),
      const SizedBox(height: 14),
      TextField(
        key: const Key('activation.confirmation'),
        controller: _confirmation,
        obscureText: _hidden,
        enableSuggestions: false,
        autocorrect: false,
        onChanged: (_) => setState(() {}),
        decoration: InputDecoration(labelText: 'Confirmation', errorText: _passwordProblem),
      ),
      const SizedBox(height: 20),
      FilledButton(
        key: const Key('activation.complete'),
        onPressed: _canComplete ? _complete : null,
        child: const Text('Activer mon compte'),
      ),
    ];
  }

  List<Widget> _done() => [
    const Icon(Icons.verified_user_outlined, size: 56, color: Tokens.success),
    const SizedBox(height: 12),
    const Text(
      'Compte activé',
      textAlign: TextAlign.center,
      style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700),
    ),
    const SizedBox(height: 8),
    Text(
      'Connectez-vous maintenant avec l\'identifiant $_activatedLogin et votre nouveau mot de passe.',
      textAlign: TextAlign.center,
      style: const TextStyle(fontSize: 15),
    ),
    const SizedBox(height: 22),
    FilledButton(
      key: const Key('activation.toLogin'),
      onPressed: () => Navigator.of(context).pop(_activatedLogin),
      child: const Text('Aller à la connexion'),
    ),
  ];
}
