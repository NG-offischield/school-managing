/// HTTP client of the Django API (`/api/v1/`). The API is the source of
/// truth: this client only sends requests and unwraps the envelope
/// `{"success", "data", "meta"}`.
///
/// - access token in memory only (`Authorization: Bearer`), never on disk;
/// - a 401 triggers ONE token refresh through [refreshHandler] (shared by
///   concurrent requests), then the request is replayed once;
/// - no network / timeout -> [NetworkException]; HTTP errors -> typed
///   [ApiException]s.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import 'api_error.dart';

class ApiPage {
  ApiPage(this.rows, this.count, {this.hasNext = false});

  final List<Map<String, dynamic>> rows;
  final int count;
  final bool hasNext;
}

class ApiClient {
  ApiClient({required String baseUrl, http.Client? client, this.timeout = const Duration(seconds: 20)})
    : baseUrl = baseUrl.endsWith('/') ? baseUrl : '$baseUrl/',
      _http = client ?? http.Client();

  final String baseUrl;
  final Duration timeout;
  final http.Client _http;

  /// Short-lived access token (memory only).
  String? accessToken;

  /// Called on a 401 to renew the access token; returns true on success.
  Future<bool> Function()? refreshHandler;
  Future<bool>? _refreshing;

  Uri uri(String path, [Map<String, Object?>? params]) {
    final query = <String, String>{};
    params?.forEach((key, value) {
      if (value != null) query[key] = '$value';
    });
    final base = Uri.parse(baseUrl).resolve(path);
    return query.isEmpty ? base : base.replace(queryParameters: query);
  }

  Future<dynamic> get(String path, {Map<String, Object?>? params}) async =>
      (await request('GET', path, params: params)).data;

  Future<dynamic> post(String path, {Object? body, bool auth = true}) async =>
      (await request('POST', path, body: body ?? const {}, auth: auth)).data;

  Future<dynamic> patch(String path, {required Object body}) async => (await request('PATCH', path, body: body)).data;

  Future<ApiPage> page(String path, {int page = 1, int pageSize = 50, Map<String, Object?>? params}) async {
    final response = await request('GET', path, params: {...?params, 'page': page, 'page_size': pageSize});
    final rows = ((response.data as List?) ?? const []).cast<Map<String, dynamic>>();
    final meta = response.meta;
    return ApiPage(rows, (meta['count'] as int?) ?? rows.length, hasNext: meta['next'] != null);
  }

  /// Every row of a paginated list (follows `meta.next`).
  Future<List<Map<String, dynamic>>> listAll(String path, {Map<String, Object?>? params}) async {
    final rows = <Map<String, dynamic>>[];
    var number = 1;
    while (true) {
      final current = await page(path, page: number, pageSize: 100, params: params);
      rows.addAll(current.rows);
      if (!current.hasNext) return rows;
      number++;
    }
  }

  Future<({dynamic data, Map<String, dynamic> meta})> request(
    String method,
    String path, {
    Object? body,
    Map<String, Object?>? params,
    bool auth = true,
    bool retry = true,
  }) async {
    if (auth && accessToken == null) {
      throw UnauthorizedException(code: 'NOT_AUTHENTICATED', message: 'Authentification requise.');
    }
    final headers = <String, String>{'Accept': 'application/json', 'Accept-Language': 'fr'};
    if (body != null) headers['Content-Type'] = 'application/json';
    if (auth) headers['Authorization'] = 'Bearer $accessToken';
    final requestObject = http.Request(method, uri(path, params))..headers.addAll(headers);
    if (body != null) requestObject.body = jsonEncode(body);
    http.Response response;
    try {
      response = await http.Response.fromStream(await _http.send(requestObject).timeout(timeout));
    } on TimeoutException {
      throw NetworkException(timeout: true);
    } on http.ClientException {
      throw NetworkException();
    } on Exception catch (error) {
      // SocketException / HandshakeException (dart:io) without importing it here.
      if ('$error'.contains('Socket') || '$error'.contains('Connection')) throw NetworkException();
      rethrow;
    }
    if (response.statusCode == 401 && auth && retry && await _refresh()) {
      return request(method, path, body: body, params: params, auth: auth, retry: false);
    }
    Map<String, dynamic>? decoded;
    if (response.bodyBytes.isNotEmpty) {
      try {
        decoded = (jsonDecode(utf8.decode(response.bodyBytes)) as Map).cast<String, dynamic>();
      } on FormatException {
        if (response.statusCode >= 500) {
          throw ServerException(status: response.statusCode, code: 'SERVER_ERROR', message: 'Erreur serveur');
        }
      }
    }
    if (response.statusCode >= 400 || decoded?['success'] == false) throw errorFor(response.statusCode, decoded);
    return (data: decoded?['data'], meta: ((decoded?['meta'] as Map?) ?? const {}).cast<String, dynamic>());
  }

  /// Binary content (PDF of a report card, receipt...), after the server's
  /// permission check. Same token / refresh / error handling as JSON calls.
  Future<Uint8List> download(String path, {Map<String, Object?>? params, bool retry = true}) async {
    if (accessToken == null) {
      throw UnauthorizedException(code: 'NOT_AUTHENTICATED', message: 'Authentification requise.');
    }
    final requestObject = http.Request('GET', uri(path, params))
      ..headers.addAll({'Accept': 'application/pdf, application/json', 'Authorization': 'Bearer $accessToken'});
    http.Response response;
    try {
      response = await http.Response.fromStream(await _http.send(requestObject).timeout(timeout));
    } on TimeoutException {
      throw NetworkException(timeout: true);
    } on http.ClientException {
      throw NetworkException();
    }
    if (response.statusCode == 401 && retry && await _refresh()) {
      return download(path, params: params, retry: false);
    }
    if (response.statusCode >= 400) {
      Map<String, dynamic>? decoded;
      try {
        decoded = (jsonDecode(utf8.decode(response.bodyBytes)) as Map).cast<String, dynamic>();
      } on FormatException {
        decoded = null;
      }
      throw errorFor(response.statusCode, decoded);
    }
    return response.bodyBytes;
  }

  /// One file sent as multipart [field] (e.g. a profile photo): the server
  /// checks its real content. Same token / refresh / error handling as JSON calls.
  Future<dynamic> upload(
    String path, {
    required String field,
    required String filename,
    required Uint8List bytes,
    bool retry = true,
  }) async {
    if (accessToken == null) {
      throw UnauthorizedException(code: 'NOT_AUTHENTICATED', message: 'Authentification requise.');
    }
    final requestObject = http.MultipartRequest('POST', uri(path))
      ..headers.addAll({'Accept': 'application/json', 'Accept-Language': 'fr', 'Authorization': 'Bearer $accessToken'})
      ..files.add(http.MultipartFile.fromBytes(field, bytes, filename: filename));
    http.Response response;
    try {
      response = await http.Response.fromStream(await _http.send(requestObject).timeout(timeout));
    } on TimeoutException {
      throw NetworkException(timeout: true);
    } on http.ClientException {
      throw NetworkException();
    }
    if (response.statusCode == 401 && retry && await _refresh()) {
      return upload(path, field: field, filename: filename, bytes: bytes, retry: false);
    }
    Map<String, dynamic>? decoded;
    try {
      decoded = (jsonDecode(utf8.decode(response.bodyBytes)) as Map).cast<String, dynamic>();
    } on FormatException {
      decoded = null;
    }
    if (response.statusCode >= 400 || decoded?['success'] == false) throw errorFor(response.statusCode, decoded);
    return decoded?['data'];
  }

  Future<bool> _refresh() {
    final handler = refreshHandler;
    if (handler == null) return Future.value(false);
    // One refresh at a time: concurrent 401s wait for the same attempt.
    return _refreshing ??= handler().catchError((_) => false).whenComplete(() => _refreshing = null);
  }

  void close() => _http.close();
}
