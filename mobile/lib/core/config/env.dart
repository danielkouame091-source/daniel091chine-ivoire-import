import 'package:flutter_dotenv/flutter_dotenv.dart' deferred as dotenv;

class Env {
  static late final String apiUrl;
  static late final String apiUrlPublic;
  static late final String environment; // dev | staging | prod
  static late final String appVersion;

  static bool get isProd => environment == 'prod';
  static bool get isDev  => environment == 'dev';

  static Future<void> load() async {
    // Chargement différé (compatible web/desktop/mobile)
    await dotenv.load(fileName: '.env');
    apiUrl       = dotenv.dotenv.get('API_URL', fallback: 'https://api.mtech.ci')!;
    apiUrlPublic = dotenv.dotenv.get('API_PUBLIC_URL', fallback: 'https://api.mtech.ci/api/v1/public')!;
    environment  = dotenv.dotenv.get('ENV', fallback: 'prod')!;
    appVersion   = dotenv.dotenv.get('APP_VERSION', fallback: '1.0.0')!;
  }
}
