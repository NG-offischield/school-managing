import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import '../api/api_error.dart';
import '../auth/auth_service.dart';
import '../theme/app_theme.dart';
import '../widgets/widgets.dart';
import '../l10n/l10n.dart';

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
      return tr('Les deux mots de passe ne sont pas identiques.');
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
      appBar: AppBar(title: Text(tr('Activer mon compte'))),
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
    Text(
      tr('Étape 1 sur 2'),
      style: TextStyle(color: Tokens.textSecondary, fontWeight: FontWeight.w600),
    ),
    const SizedBox(height: 6),
    Text(
      tr('Saisissez le code d\'activation remis par l\'administration de votre établissement.'),
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
      decoration: InputDecoration(labelText: tr('Code d\'activation'), hintText: 'XXXX-XXXX-XXXX-XXXX-XXXX'),
      onChanged: (_) => setState(() {}),
      onSubmitted: (_) => _code.text.trim().isEmpty ? null : _check(),
    ),
    const SizedBox(height: 20),
    FilledButton(
      key: const Key('activation.check'),
      onPressed: _busy || _code.text.trim().isEmpty ? null : _check,
      child: Text(tr('Vérifier le code')),
    ),
  ];

  List<Widget> _passwordStep() {
    final preview = _preview!;
    final expires = preview.expiresAt == null
        ? ''
        : DateFormat('dd/MM/yyyy HH:mm', L10n.intl).format(preview.expiresAt!.toLocal());
    return [
      Text(
        tr('Étape 2 sur 2'),
        style: TextStyle(color: Tokens.textSecondary, fontWeight: FontWeight.w600),
      ),
      const SizedBox(height: 6),
      Text(tr('Bonjour {0},', [preview.firstName]), style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
      const SizedBox(height: 6),
      Text(
        tr('Établissement : {0}\nIdentifiant : {1}{2}', [
          preview.school,
          preview.login,
          expires.isEmpty ? '' : tr('\nCode valable jusqu\'au {0}', [expires]),
        ]),
        style: const TextStyle(fontSize: 15, height: 1.4),
      ),
      const SizedBox(height: 18),
      Text(
        tr('Choisissez votre mot de passe : au moins 10 caractères, ni trop courant, ni proche de votre nom.'),
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
          labelText: tr('Nouveau mot de passe'),
          suffixIcon: IconButton(
            tooltip: _hidden ? tr('Afficher') : tr('Masquer'),
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
        decoration: InputDecoration(labelText: tr('Confirmation'), errorText: _passwordProblem),
      ),
      const SizedBox(height: 20),
      FilledButton(
        key: const Key('activation.complete'),
        onPressed: _canComplete ? _complete : null,
        child: Text(tr('Activer mon compte')),
      ),
    ];
  }

  List<Widget> _done() => [
    Icon(Icons.verified_user_outlined, size: 56, color: Tokens.success),
    const SizedBox(height: 12),
    Text(
      tr('Compte activé'),
      textAlign: TextAlign.center,
      style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700),
    ),
    const SizedBox(height: 8),
    Text(
      tr('Connectez-vous maintenant avec l\'identifiant {0} et votre nouveau mot de passe.', [_activatedLogin]),
      textAlign: TextAlign.center,
      style: const TextStyle(fontSize: 15),
    ),
    const SizedBox(height: 22),
    FilledButton(
      key: const Key('activation.toLogin'),
      onPressed: () => Navigator.of(context).pop(_activatedLogin),
      child: Text(tr('Aller à la connexion')),
    ),
  ];
}
