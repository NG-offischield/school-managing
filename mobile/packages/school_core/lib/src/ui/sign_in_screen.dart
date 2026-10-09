import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/api_error.dart';
import '../auth/auth_service.dart';
import '../theme/app_theme.dart';
import '../widgets/widgets.dart';
import 'activation_screen.dart';
import 'server_settings.dart';

/// Second way in, under the sign-in form: account activation (accounts
/// created by the school) or self-registration (parents). The screen it
/// opens returns the login identifier to prefill, or null.
class SignInAlternative {
  const SignInAlternative({
    required this.hint,
    required this.label,
    required this.icon,
    required this.key,
    required this.open,
  });

  /// Activation of an account created by the school (ADR 0024).
  factory SignInAlternative.activation() => SignInAlternative(
    hint: 'Première connexion ? L\'administration vous a remis un code d\'activation.',
    label: 'Activer mon compte',
    icon: Icons.key_outlined,
    key: const Key('login.activate'),
    open: (context) => Navigator.of(context).push<String>(MaterialPageRoute(builder: (_) => const ActivationScreen())),
  );

  final String hint;
  final String label;
  final IconData icon;
  final Key key;
  final Future<String?> Function(BuildContext context) open;
}

/// Identifier + password -> /auth/login/ (the one authentication of every
/// app). The password lives only in the text field while typing; it is never
/// stored. `roleLabel` explains a refused account of another role.
class SignInScreen extends StatefulWidget {
  const SignInScreen({
    super.key,
    required this.subtitle,
    required this.roleLabel,
    required this.alternative,
    this.identifier,
  });

  final String subtitle;
  final String roleLabel;
  final SignInAlternative alternative;
  final String? identifier;

  @override
  State<SignInScreen> createState() => _SignInScreenState();
}

class _SignInScreenState extends State<SignInScreen> {
  late final _identifier = TextEditingController(text: widget.identifier);
  final _password = TextEditingController();
  bool _hidden = true;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _identifier.dispose();
    _password.dispose();
    super.dispose();
  }

  bool get _ready => _identifier.text.trim().isNotEmpty && _password.text.isNotEmpty && !_busy;

  Future<void> _submit() async {
    if (!_ready) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    final auth = context.read<AuthService>();
    try {
      await auth.login(_identifier.text, _password.text);
    } on WrongRoleException {
      _error = 'Ce compte n\'est pas un compte ${widget.roleLabel} : utilisez l\'application prévue pour votre rôle.';
    } on ApiException catch (error) {
      _error = error.userMessage;
    } finally {
      _password.clear();
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _alternative() async {
    final login = await widget.alternative.open(context);
    if (login != null && mounted) {
      setState(() {
        _identifier.text = login;
        _error = null;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthService>();
    final notice = auth.notice;
    final server = Uri.parse(auth.api.baseUrl);
    final alternative = widget.alternative;
    return Scaffold(
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, constraints) => SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(24, 32, 24, 24),
            child: ConstrainedBox(
              constraints: BoxConstraints(minHeight: constraints.maxHeight - 56),
              child: Center(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 440),
                  child: AutofillGroup(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        SoftwareBrand(subtitle: widget.subtitle),
                        const SizedBox(height: 32),
                        if (notice != null && _error == null) ...[
                          MessageBanner(notice, tone: Tone.info),
                          const SizedBox(height: 16),
                        ],
                        if (_error != null) ...[MessageBanner(_error!), const SizedBox(height: 16)],
                        TextField(
                          key: const Key('login.identifier'),
                          controller: _identifier,
                          keyboardType: TextInputType.emailAddress,
                          autofillHints: const [AutofillHints.username, AutofillHints.email],
                          textInputAction: TextInputAction.next,
                          autocorrect: false,
                          decoration: const InputDecoration(
                            labelText: 'Identifiant (e-mail)',
                            prefixIcon: Icon(Icons.person_outline),
                          ),
                          onChanged: (_) => setState(() {}),
                        ),
                        const SizedBox(height: 14),
                        TextField(
                          key: const Key('login.password'),
                          controller: _password,
                          obscureText: _hidden,
                          autofillHints: const [AutofillHints.password],
                          textInputAction: TextInputAction.done,
                          enableSuggestions: false,
                          autocorrect: false,
                          onSubmitted: (_) => _submit(),
                          onChanged: (_) => setState(() {}),
                          decoration: InputDecoration(
                            labelText: 'Mot de passe',
                            prefixIcon: const Icon(Icons.lock_outline),
                            suffixIcon: IconButton(
                              tooltip: _hidden ? 'Afficher le mot de passe' : 'Masquer le mot de passe',
                              icon: Icon(_hidden ? Icons.visibility_outlined : Icons.visibility_off_outlined),
                              onPressed: () => setState(() => _hidden = !_hidden),
                            ),
                          ),
                        ),
                        const SizedBox(height: 22),
                        FilledButton(
                          key: const Key('login.submit'),
                          onPressed: _ready ? _submit : null,
                          child: _busy
                              ? const SizedBox(
                                  width: 22,
                                  height: 22,
                                  child: CircularProgressIndicator(strokeWidth: 2.5, color: Colors.white),
                                )
                              : const Text('Se connecter'),
                        ),
                        const SizedBox(height: 18),
                        const Divider(),
                        const SizedBox(height: 8),
                        Text(
                          alternative.hint,
                          textAlign: TextAlign.center,
                          style: const TextStyle(color: Tokens.textSecondary),
                        ),
                        const SizedBox(height: 10),
                        OutlinedButton.icon(
                          key: alternative.key,
                          onPressed: _busy ? null : _alternative,
                          icon: Icon(alternative.icon),
                          label: Text(alternative.label),
                        ),
                        const SizedBox(height: 18),
                        // Which backend this build talks to: the first thing to check on a LAN setup.
                        Text(
                          'Serveur : ${server.hasPort ? '${server.host}:${server.port}' : server.host}',
                          key: const Key('login.server'),
                          textAlign: TextAlign.center,
                          style: const TextStyle(color: Tokens.textSecondary, fontSize: 12),
                        ),
                        // Another network, another PC address: change it here, no rebuild (ServerHost).
                        if (ServerScope.maybeOf(context) case final control?)
                          TextButton.icon(
                            key: const Key('login.server.change'),
                            onPressed: _busy ? null : () => openServerSettings(context, control),
                            icon: const Icon(Icons.dns_outlined, size: 18),
                            label: const Text('Changer de serveur'),
                          ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
