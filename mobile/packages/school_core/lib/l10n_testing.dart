/// Localization checks for the apps' tests (not part of the runtime API):
///
/// - [frenchKeys]: every French key of a package's code — tr calls and the
///   label tables `_xxxFr` — so a test can require an English text for each
///   one (no missing translation, no blank);
/// - [visibleTexts] + [frenchLooking]: what the screen REALLY shows, to fail
///   when a French text escaped the system once the app is in English.
library;

import 'dart:io';

import 'package:flutter/widgets.dart';

export 'src/l10n/core_en.dart' show coreEnglish;

String _decode(String seg) => seg
    .replaceAllMapped(RegExp(r'\\x([0-9a-fA-F]{2})'), (m) => String.fromCharCode(int.parse(m[1]!, radix: 16)))
    .replaceAllMapped(RegExp(r'\\(.)'), (m) {
      const map = {'n': '\n', 't': '\t', "'": "'", '"': '"', r'\': r'\', r'$': r'$'};
      return map[m[1]] ?? m[1]!;
    });

final _piece = RegExp(r"'((?:[^'\\]|\\.)*)'");
final _trCall = RegExp(r"\btr\(\s*((?:'(?:[^'\\]|\\.)*'\s*)+)");
final _frMap = RegExp(r'const _\w+Fr\s*=\s*(?:<[^>]+>)?\{([\s\S]*?)\n?\};');
final _mapValue = RegExp(r":\s*((?:'(?:[^'\\]|\\.)*'\s*)+)[,\n}]");
final _comment = RegExp(r'^\s*//.*$', multiLine: true);

String _join(String pieces) => _piece.allMatches(pieces).map((m) => _decode(m[1]!)).join();

/// The French keys used by the Dart files under [libDir] (comments ignored).
Set<String> frenchKeys(String libDir) {
  final keys = <String>{};
  for (final file in Directory(libDir).listSync(recursive: true).whereType<File>()) {
    if (!file.path.endsWith('.dart')) continue;
    final src = file.readAsStringSync().replaceAll(_comment, '');
    for (final m in _trCall.allMatches(src)) {
      keys.add(_join(m[1]!));
    }
    for (final m in _frMap.allMatches(src)) {
      for (final v in _mapValue.allMatches('${m[1]},')) {
        keys.add(_join(v[1]!));
      }
    }
  }
  return keys;
}

/// Every text currently built on screen (Text, RichText).
List<String> visibleTexts() {
  final texts = <String>[];
  void visit(Element element) {
    final widget = element.widget;
    if (widget is Text) {
      texts.add(widget.data ?? widget.textSpan?.toPlainText() ?? '');
    } else if (widget is RichText) {
      texts.add(widget.text.toPlainText());
    }
    element.visitChildren(visit);
  }

  WidgetsBinding.instance.rootElement?.visitChildren(visit);
  return texts.where((t) => t.trim().isNotEmpty).toList();
}

final _frenchWords = RegExp(
  r"\b(le|la|les|des|du|une|aucun|aucune|vos|votre|vous|nous|pour|avec|dans|est|sont|mes|cette|ces|et|ou|pas|sur|par|au|aux|d'|l'|qu'|n'|s')\b|[àâçéèêëîïôûùüÿœ]",
  caseSensitive: false,
);

/// Texts that look French, minus business data the test lists in [allowed]
/// (names of people and schools, typed messages: never translated).
List<String> frenchLooking(Iterable<String> texts, {Set<String> allowed = const {}}) =>
    texts.where((t) => _frenchWords.hasMatch(allowed.fold(t, (s, a) => s.replaceAll(a, '')))).toList();
