import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import '../../data/parent_repository.dart';

/// « Créer mon compte » (spec §6.3): the parent chooses their own password
/// (checked by the server's rules); the account then waits for the
/// school's validation. The server answers the same way whatever happens
/// (an e-mail already used is never revealed). Returns the e-mail to log in.
class RegisterScreen extends StatefulWidget {
  const RegisterScreen({super.key});

  @override
  State<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends State<RegisterScreen> {
  final _first = TextEditingController();
  final _last = TextEditingController();
  final _email = TextEditingController();
  final _phone = TextEditingController();
  final _password = TextEditingController();
  final _confirmation = TextEditingController();
  bool _hidden = true;
  bool _busy = false;
  bool _done = false;
  String? _error;
  Map<String, List<String>> _fieldErrors = const {};

  @override
  void dispose() {
    for (final c in [_first, _last, _email, _phone, _password, _confirmation]) {
      c.dispose();
    }
    super.dispose();
  }

  bool get _matches => _password.text == _confirmation.text;

  bool get _ready =>
      !_busy &&
      _first.text.trim().isNotEmpty &&
      _last.text.trim().isNotEmpty &&
      _email.text.contains('@') &&
      _password.text.isNotEmpty &&
      _matches;

  Future<void> _submit() async {
    if (!_ready) return;
    setState(() {
      _busy = true;
      _error = null;
      _fieldErrors = const {};
    });
    try {
      await context.read<ParentRepository>().register(
        firstName: _first.text,
        lastName: _last.text,
        email: _email.text,
        password: _password.text,
        phone: _phone.text,
      );
      _done = true;
    } on ApiException catch (error) {
      _error = error.userMessage;
      _fieldErrors = error.fieldErrors;
    } finally {
      _password.clear();
      _confirmation.clear();
      if (mounted) setState(() => _busy = false);
    }
  }

  String? _fieldError(String name) {
    final messages = _fieldErrors[name];
    return messages == null || messages.isEmpty ? null : messages.join(' ');
  }

  Widget _field(
    String key,
    TextEditingController controller,
    String label,
    IconData icon, {
    TextInputType? keyboard,
    List<String>? autofill,
    String? field,
  }) => Padding(
    padding: const EdgeInsets.only(bottom: 14),
    child: TextField(
      key: Key('register.$key'),
      controller: controller,
      keyboardType: keyboard,
      autofillHints: autofill,
      textInputAction: TextInputAction.next,
      onChanged: (_) => setState(() {}),
      decoration: InputDecoration(labelText: label, prefixIcon: Icon(icon), errorText: _fieldError(field ?? key)),
    ),
  );

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Créer mon compte')),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 480),
              child: _done ? _received(context) : _form(context),
            ),
          ),
        ),
      ),
    );
  }

  Widget _received(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      const Icon(Icons.mark_email_read_outlined, size: 56, color: Tokens.success),
      const SizedBox(height: 16),
      const Text(
        'Demande enregistrée',
        textAlign: TextAlign.center,
        style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
      ),
      const SizedBox(height: 10),
      const Text(
        'L\'établissement va valider votre compte. Vous pouvez déjà vous connecter pour suivre la demande ; '
        'vous rattacherez ensuite votre enfant (pièce d\'identité vérifiée à l\'école).',
        textAlign: TextAlign.center,
        style: TextStyle(color: Tokens.textSecondary),
      ),
      const SizedBox(height: 22),
      FilledButton(
        key: const Key('register.back'),
        onPressed: () => Navigator.of(context).pop(_email.text.trim()),
        child: const Text('Aller à la connexion'),
      ),
    ],
  );

  Widget _form(BuildContext context) => AutofillGroup(
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Text(
          'Votre compte sera validé par l\'établissement. Aucune donnée d\'élève n\'est visible avant la '
          'vérification de votre lien avec l\'enfant.',
          style: TextStyle(color: Tokens.textSecondary),
        ),
        const SizedBox(height: 16),
        if (_error != null) ...[MessageBanner(_error!), const SizedBox(height: 14)],
        _field('first_name', _first, 'Prénom', Icons.badge_outlined, autofill: const [AutofillHints.givenName]),
        _field('last_name', _last, 'Nom', Icons.badge_outlined, autofill: const [AutofillHints.familyName]),
        _field(
          'email',
          _email,
          'E-mail (identifiant)',
          Icons.alternate_email,
          keyboard: TextInputType.emailAddress,
          autofill: const [AutofillHints.email],
        ),
        _field(
          'phone',
          _phone,
          'Téléphone (facultatif)',
          Icons.phone_outlined,
          keyboard: TextInputType.phone,
          autofill: const [AutofillHints.telephoneNumber],
        ),
        TextField(
          key: const Key('register.password'),
          controller: _password,
          obscureText: _hidden,
          enableSuggestions: false,
          autocorrect: false,
          autofillHints: const [AutofillHints.newPassword],
          onChanged: (_) => setState(() {}),
          decoration: InputDecoration(
            labelText: 'Mot de passe',
            helperText: 'Au moins 10 caractères, pas uniquement des chiffres.',
            errorText: _fieldError('password'),
            errorMaxLines: 3,
            prefixIcon: const Icon(Icons.lock_outline),
            suffixIcon: IconButton(
              tooltip: _hidden ? 'Afficher le mot de passe' : 'Masquer le mot de passe',
              icon: Icon(_hidden ? Icons.visibility_outlined : Icons.visibility_off_outlined),
              onPressed: () => setState(() => _hidden = !_hidden),
            ),
          ),
        ),
        const SizedBox(height: 14),
        TextField(
          key: const Key('register.confirmation'),
          controller: _confirmation,
          obscureText: _hidden,
          enableSuggestions: false,
          autocorrect: false,
          onChanged: (_) => setState(() {}),
          onSubmitted: (_) => _submit(),
          decoration: InputDecoration(
            labelText: 'Confirmer le mot de passe',
            prefixIcon: const Icon(Icons.lock_outline),
            errorText: _confirmation.text.isNotEmpty && !_matches ? 'Les deux mots de passe diffèrent.' : null,
          ),
        ),
        const SizedBox(height: 22),
        FilledButton(
          key: const Key('register.submit'),
          onPressed: _ready ? _submit : null,
          child: _busy
              ? const SizedBox(
                  width: 22,
                  height: 22,
                  child: CircularProgressIndicator(strokeWidth: 2.5, color: Colors.white),
                )
              : const Text('Créer mon compte'),
        ),
      ],
    ),
  );
}
