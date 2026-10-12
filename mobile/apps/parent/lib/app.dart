import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import 'data/parent_repository.dart';
import 'data/pdf_store.dart';
import 'presentation/auth/register_screen.dart';
import 'presentation/auth/pending_screen.dart';
import 'presentation/home/home_shell.dart';

/// Root: the session state decides the screen
/// (splash -> login / create account -> pending approval -> home).
class ParentApp extends StatelessWidget {
  const ParentApp({
    super.key,
    required this.auth,
    required this.repository,
    required this.pdfStore,
    this.planFiles = const DevicePlanFiles(),
    this.realtime,
  });

  final AuthService auth;
  final ParentRepository repository;
  final PdfStore pdfStore;

  /// Where a PDF school plan goes to be shown by the phone's viewer (school_core).
  final PlanFiles planFiles;

  /// Live connection (existing ws/v1/realtime/); null = refresh by hand (tests).
  final RealtimeClient Function()? realtime;

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider<AuthService>.value(value: auth),
        Provider<ParentRepository>.value(value: repository),
        Provider<CommunicationRepository>.value(value: repository),
        Provider<PdfStore>.value(value: pdfStore),
        Provider<PlanFiles>.value(value: planFiles),
      ],
      child: MaterialApp(
        title: 'School Managing — Parent',
        debugShowCheckedModeBanner: false,
        theme: buildAppTheme(),
        darkTheme: buildAppTheme(brightness: Brightness.dark),
        themeMode: themeModeOf(context),
        builder: themedScreens,
        locale: const Locale('fr', 'FR'),
        supportedLocales: const [Locale('fr', 'FR')],
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        home: AuthGate(realtime: realtime),
      ),
    );
  }
}

class AuthGate extends StatefulWidget {
  const AuthGate({super.key, this.realtime});

  final RealtimeClient Function()? realtime;

  @override
  State<AuthGate> createState() => _AuthGateState();
}

class _AuthGateState extends State<AuthGate> {
  late final AuthService _auth;
  AuthStatus? _last;

  @override
  void initState() {
    super.initState();
    _auth = context.read<AuthService>()..addListener(_closeScreensOnSignOut);
  }

  /// Logout / expired session: screens opened above the shell (a
  /// conversation, a report card...) are closed with it.
  void _closeScreensOnSignOut() {
    final status = _auth.status;
    if (status != _last && status != AuthStatus.signedIn && mounted) {
      Navigator.of(context).popUntil((route) => route.isFirst);
    }
    _last = status;
  }

  @override
  void dispose() {
    _auth.removeListener(_closeScreensOnSignOut);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthService>();
    final realtime = widget.realtime;
    return switch (auth.status) {
      AuthStatus.restoring => const SplashScreen(),
      AuthStatus.signedOut => SignInScreen(
        subtitle: 'Espace parent',
        roleLabel: 'parent',
        alternative: SignInAlternative(
          hint: 'Nouveau parent ? Créez votre compte : l\'établissement le validera.',
          label: 'Créer mon compte',
          icon: Icons.person_add_alt_1_outlined,
          key: const Key('login.register'),
          open: (context) =>
              Navigator.of(context).push<String>(MaterialPageRoute(builder: (_) => const RegisterScreen())),
        ),
      ),
      AuthStatus.pending => const PendingScreen(),
      AuthStatus.signedIn => HomeShell(key: ValueKey(auth.identity?.userId), realtime: realtime),
    };
  }
}

class SplashScreen extends StatelessWidget {
  const SplashScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Tokens.navy,
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            SoftwareBrand(light: true, size: 30, subtitle: 'Espace parent'),
            SizedBox(height: 28),
            CircularProgressIndicator(color: Colors.white, semanticsLabel: 'Ouverture de la session'),
          ],
        ),
      ),
    );
  }
}
