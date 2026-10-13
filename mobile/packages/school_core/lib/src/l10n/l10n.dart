/// Français / English for the four apps (school_core + each app).
///
/// The FRENCH text is the key: `tr('Se déconnecter')`. French is the default
/// language and the explicit fallback; English comes from catalogs — the
/// shared one of school_core ([coreEnglish]) and each app's own one
/// ([L10n.register]). Placeholders are positional: `tr('Version {0}', [n])`.
///
/// Only the INTERFACE is translated: names, school names, messages typed by
/// people, amounts and dates sent to the server are never touched.
/// The choice is a local preference of the installation ([LanguageController],
/// shared_preferences): kept across sign-out, server switch and restart, never
/// sent to the profile. The server answers in the same language
/// (Accept-Language) for its own validation messages.
library;

import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'core_en.dart';

enum AppLanguage {
  fr('fr', 'fr_FR', 'Français'),
  en('en', 'en_US', 'English');

  const AppLanguage(this.code, this.intl, this.label);

  /// HTTP Accept-Language / Locale language code.
  final String code;

  /// intl locale for dates and numbers.
  final String intl;

  /// Shown in its own language in the selector.
  final String label;

  Locale get locale => Locale(code);
}

abstract final class L10n {
  static AppLanguage _language = AppLanguage.fr;
  static final Map<String, String> _english = {...coreEnglish};
  static final Set<String> _englishTexts = {...coreEnglish.values};

  /// Keys asked in English without a translation (tests fail on them).
  static final Set<String> missing = {};

  static AppLanguage get language => _language;
  static bool get isEnglish => _language == AppLanguage.en;
  static String get intl => _language.intl;

  /// Tests / [LocalizedScreens] only.
  static void use(AppLanguage language) {
    _language = language;
    changes.value = language;
  }

  /// The language in use, for what lives outside the widget tree (the
  /// real-time connection announces it to the server).
  static final ValueNotifier<AppLanguage> changes = ValueNotifier(AppLanguage.fr);

  /// An app adds its own English texts (idempotent).
  static final Set<Map<String, String>> _registered = {};

  static void register(Map<String, String> english) {
    if (!_registered.add(english)) return; // the same const catalog: already merged
    _english.addAll(english);
    _englishTexts.addAll(english.values);
  }

  static bool has(String french) => _english.containsKey(french);

  static String translate(String french) {
    if (_language == AppLanguage.fr) return french;
    final english = _english[french];
    if (english != null) return english;
    if (_englishTexts.contains(french)) return french; // already translated (tr is idempotent)
    missing.add(french);
    return french; // fallback, never a blank
  }
}

/// The interface text for [french] in the current language, `{0}`, `{1}`…
/// replaced by [args] (left untouched: names, numbers, dates already formatted).
String tr(String french, [List<Object?> args = const []]) {
  var text = L10n.translate(french);
  for (var i = 0; i < args.length; i++) {
    text = text.replaceAll('{$i}', '${args[i] ?? ''}');
  }
  return text;
}

/// A label table (code -> French) read in the current language.
Map<K, String> trMap<K>(Map<K, String> french) => french.map((k, v) => MapEntry(k, tr(v)));

/// The user's language, kept on the phone. Default: French.
class LanguageController extends ChangeNotifier {
  LanguageController({AppLanguage initial = AppLanguage.fr}) : _language = initial;

  static const key = 'school_managing.language';

  AppLanguage _language;
  AppLanguage get language => _language;

  static Future<LanguageController> load() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = AppLanguage.values.where((l) => l.code == prefs.getString(key)).firstOrNull;
    return LanguageController(initial: saved ?? AppLanguage.fr);
  }

  Future<void> set(AppLanguage language) async {
    if (language == _language) return;
    _language = language;
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(key, language.code);
  }
}

/// The language for an app's MaterialApp (French when no controller: widget tests).
AppLanguage languageOf(BuildContext context) => context.watch<LanguageController?>()?.language ?? L10n.language;

/// Locales the apps support (Material widgets: date pickers, buttons…).
const supportedAppLocales = [Locale('fr'), Locale('en')];

/// Below MaterialApp: keeps [L10n] on the chosen language and, when it
/// changes, rebuilds every open screen so their texts follow — navigation and
/// typed values kept.
class LocalizedScreens extends StatefulWidget {
  const LocalizedScreens({super.key, required this.language, required this.child});

  final AppLanguage language;
  final Widget child;

  @override
  State<LocalizedScreens> createState() => _LocalizedScreensState();
}

class _LocalizedScreensState extends State<LocalizedScreens> {
  AppLanguage? _applied;

  @override
  Widget build(BuildContext context) {
    if (_applied != widget.language) {
      final first = _applied == null;
      _applied = widget.language;
      L10n.use(widget.language);
      if (!first) {
        SchedulerBinding.instance.addPostFrameCallback((_) {
          if (!mounted) return;
          void rebuild(Element element) {
            element.markNeedsBuild();
            element.visitChildren(rebuild);
          }

          (context as Element).visitChildren(rebuild);
        });
      }
    }
    return widget.child;
  }
}
