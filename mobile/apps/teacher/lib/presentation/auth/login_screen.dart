import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import 'activation_screen.dart';

/// Identifier + password -> /auth/login/. The password lives only in the
/// text field while typing; it is never stored.
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key, this.identifier});

  final String? identifier;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
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
      _error = 'Ce compte n\'est pas un compte enseignant : utilisez l\'application prévue pour votre rôle.';
    } on ApiException catch (error) {
      _error = error.userMessage;
    } finally {
      _password.clear();
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _activate() async {
    final login = await Navigator.of(context).push<String>(MaterialPageRoute(builder: (_) => const ActivationScreen()));
    if (login != null && mounted) {
      setState(() {
        _identifier.text = login;
        _error = null;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final notice = context.watch<AuthService>().notice;
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
                        const SoftwareBrand(subtitle: 'Espace enseignant'),
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
                        const Text(
                          'Première connexion ? L\'administration vous a remis un code d\'activation.',
                          textAlign: TextAlign.center,
                          style: TextStyle(color: Tokens.textSecondary),
                        ),
                        const SizedBox(height: 10),
                        OutlinedButton.icon(
                          key: const Key('login.activate'),
                          onPressed: _busy ? null : _activate,
                          icon: const Icon(Icons.key_outlined),
                          label: const Text('Activer mon compte'),
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
