import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:hive_flutter/hive_flutter.dart';
import 'package:firebase_core/firebase_core.dart';

import 'app.dart';
import 'core/config/env.dart';
import 'core/storage/hive_boxes.dart';
import 'core/notifications/push_service.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Orientation portrait uniquement (app dirigeant)
  await SystemChrome.setPreferredOrientations([
    DeviceOrientation.portraitUp,
    DeviceOrientation.portraitDown,
  ]);

  // Statut bar transparent
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
    statusBarColor: Colors.transparent,
    statusBarIconBrightness: Brightness.dark,
  ));

  // Hive (offline cache)
  await Hive.initFlutter();
  await HiveBoxes.open();

  // Firebase (push)
  try {
    await Firebase.initializeApp();
    await PushService.init();
  } catch (_) {
    // Ignore en dev sans config Firebase
  }

  // Env
  await Env.load();

  runApp(const ProviderScope(child: MTechApp()));
}
