import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:provider/provider.dart';
import 'package:school_core/l10n_testing.dart';
import 'package:school_core/school_core.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'account_test.dart' show FakeAccountServer, pumpAccountWith;
import 'plans_test.dart' show FakeServer, planJson;

/// Français / English in school_core: every French key of the code has an
/// English text, placeholders match, the shared screens rendered in English
/// show no French text left, a switch applies at once (open screens, typed
/// values kept) and the choice is kept on the phone, independently of the theme.
/// Widget tests — not E2E.

/// Business data (never translated) and the language names, written in their own language.
const businessData = {
  'Français',
  'Entrée principale au nord.',
  'Awa Mbarga',
  'awa@parents.test',
  'École Test',
  'Lycée Test',
  'Plan général',
  'Annexe',
  'Bâtiment A',
};

void main() {
  setUpAll(() => initializeDateFormatting());
  tearDown(() => L10n.use(AppLanguage.fr));

  test('every French key of school_core has an English text, with the same placeholders', () {
    final keys = frenchKeys('lib');
    expect(keys.length, greaterThan(250));
    final missing = keys.where((k) => !coreEnglish.containsKey(k)).toList();
    expect(missing, isEmpty, reason: 'missing English: $missing');
    final placeholders = RegExp(r'\{\d+\}');
    for (final entry in coreEnglish.entries) {
      final fr = placeholders.allMatches(entry.key).map((m) => m[0]).toList()..sort();
      final en = placeholders.allMatches(entry.value).map((m) => m[0]).toList()..sort();
      expect(en, fr, reason: entry.key);
      expect(entry.value.trim(), isNotEmpty, reason: entry.key);
    }
  });

  test('tr: French by default, English when chosen, placeholders filled, data untouched', () {
    expect(tr('Se déconnecter'), 'Se déconnecter');
    L10n.use(AppLanguage.en);
    expect(tr('Se déconnecter'), 'Sign out');
    expect(tr('Bonjour {0},', ['Awa']), 'Hello Awa,');
    expect(tr(tr('Se déconnecter')), 'Sign out'); // idempotent: no false « missing »
    expect(tr('Awa Mbarga'), 'Awa Mbarga'); // a name is never translated
    expect(notificationTypes['PAYMENT'], 'Payment');
    expect(formatMoney('15000.00').replaceAll(' ', ' '), '15 000 XAF'); // amounts and currency unchanged
    L10n.missing.clear();
  });

  testWidgets('« Mon compte » in English: no French text left', (tester) async {
    L10n.use(AppLanguage.en);
    await pumpAccountWith(tester, FakeAccountServer(), theme: ThemeController());
    for (final key in ['account.password', 'account.sessions']) {
      await tester.scrollUntilVisible(find.byKey(Key(key)), 200, scrollable: find.byType(Scrollable).first);
    }
    final texts = visibleTexts();
    expect(texts, contains('My account'));
    expect(frenchLooking(texts, allowed: businessData), isEmpty);
    expect(L10n.missing, isEmpty);
  });

  testWidgets('plans, communication, sign-in and server settings in English: no French text left', (tester) async {
    L10n.use(AppLanguage.en);
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 2.6;
    addTearDown(tester.view.reset);
    final server = FakeServer({'p1': planJson('p1', 'Plan général')});
    final repo = CommunicationRepository(server.api());
    Future<void> show(Widget screen) async {
      await tester.pumpWidget(
        MultiProvider(
          providers: [
            ChangeNotifierProvider<LiveState>(create: (_) => LiveState()),
            Provider<CommunicationRepository>.value(value: repo),
            Provider<PlanFiles>.value(value: MemoryPlanFiles()),
          ],
          child: MaterialApp(
            locale: const Locale('en'),
            supportedLocales: supportedAppLocales,
            localizationsDelegates: GlobalMaterialLocalizations.delegates,
            home: screen,
          ),
        ),
      );
      await tester.pumpAndSettle();
      final french = frenchLooking(visibleTexts(), allowed: businessData);
      expect(french, isEmpty, reason: '${screen.runtimeType}: $french');
    }

    await show(const PlansScreen());
    await show(const PlanViewerScreen(planId: 'p1'));
    await show(const CommunicationScreen(messaging: false, complaints: false));
    expect(L10n.missing, isEmpty);
  });

  testWidgets('switching the language applies at once, keeps what was typed, and is kept on the phone', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final language = await LanguageController.load();
    final theme = ThemeController(initial: ThemeMode.dark);
    expect(language.language, AppLanguage.fr); // French by default
    final typed = TextEditingController(text: 'Ma réponse');
    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider<LanguageController>.value(value: language),
          ChangeNotifierProvider<ThemeController>.value(value: theme),
        ],
        child: Builder(
          builder: (context) => MaterialApp(
            theme: buildAppTheme(),
            darkTheme: buildAppTheme(brightness: Brightness.dark),
            themeMode: themeModeOf(context),
            locale: languageOf(context).locale,
            supportedLocales: supportedAppLocales,
            localizationsDelegates: GlobalMaterialLocalizations.delegates,
            builder: themedScreens,
            home: Scaffold(
              body: Column(
                children: [
                  const _Probe(),
                  TextField(controller: typed),
                  const LanguageChoice(),
                ],
              ),
            ),
          ),
        ),
      ),
    );
    expect(find.text('Se déconnecter'), findsOneWidget);
    await tester.tap(find.byKey(const Key('account.language.en')));
    await tester.pumpAndSettle();
    expect(find.text('Sign out'), findsOneWidget);
    expect(find.text('Language'), findsOneWidget);
    expect(find.text('Ma réponse'), findsOneWidget); // typed value kept
    expect(Localizations.localeOf(tester.element(find.byType(TextField))).languageCode, 'en'); // Material texts too
    expect(Tokens.isDark, isTrue); // the theme is independent
    expect((await SharedPreferences.getInstance()).getString(LanguageController.key), 'en');
    expect((await LanguageController.load()).language, AppLanguage.en); // restored at the next start
    await tester.tap(find.byKey(const Key('account.language.fr')));
    await tester.pumpAndSettle();
    expect(find.text('Se déconnecter'), findsOneWidget);
    Tokens.use(Brightness.light);
  });

  test('an unknown saved value falls back to French', () async {
    SharedPreferences.setMockInitialValues({LanguageController.key: 'de'});
    expect((await LanguageController.load()).language, AppLanguage.fr);
  });

  test('requests carry the chosen language (Accept-Language): the server answers in it', () async {
    final sent = <String?>[];
    final api = ApiClient(
      baseUrl: 'http://h/api/v1/',
      client: MockClient((request) async {
        sent.add(request.headers['Accept-Language']);
        return http.Response('{"success": true, "data": null}', 200, headers: {'content-type': 'application/json'});
      }),
    )..accessToken = 'acc';
    await api.get('auth/me/');
    L10n.use(AppLanguage.en);
    await api.get('auth/me/');
    await api.download('auth/me/photo/');
    expect(sent, ['fr', 'en', 'en']);
  });
}

class _Probe extends StatelessWidget {
  const _Probe();

  @override
  Widget build(BuildContext context) => Text(tr('Se déconnecter'));
}
