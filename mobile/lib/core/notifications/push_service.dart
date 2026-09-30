import 'dart:io';

import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:go_router/go_router.dart';

import '../network/api_client.dart';

class PushService {
  static final _localNotif = FlutterLocalNotificationsPlugin();
  static const _channel = AndroidNotificationChannel(
    'mtech_default',
    'MTech Notifications',
    description: 'Notifications MTech',
    importance: Importance.high,
  );

  static Future<void> init() async {
    // Permission iOS
    final settings = await FirebaseMessaging.instance.requestPermission(
      alert: true, badge: true, sound: true,
    );
    if (settings.authorizationStatus != AuthorizationStatus.authorized) return;

    // Canal Android
    final android = _localNotif.resolvePlatformSpecificImplementation<
        AndroidFlutterLocalNotificationsPlugin>();
    await android?.createNotificationChannel(_channel);

    // Init plugin local
    const androidInit = AndroidInitializationSettings('@mipmap/ic_launcher');
    const iosInit = DarwinInitializationSettings();
    await _localNotif.initialize(
      const InitializationSettings(android: androidInit, iOS: iosInit),
      onDidReceiveNotificationResponse: (response) => _handlePayload(response.payload),
    );

    // Foreground message
    FirebaseMessaging.onMessage.listen(_onForegroundMessage);

    // Token
    final token = await FirebaseMessaging.instance.getToken();
    if (token != null) await _registerToken(token);
  }

  static Future<void> _onForegroundMessage(RemoteMessage message) async {
    final notif = message.notification;
    if (notif == null) return;

    await _localNotif.show(
      notif.hashCode,
      notif.title,
      notif.body,
      NotificationDetails(
        android: AndroidNotificationDetails(
          _channel.id, _channel.name,
          channelDescription: _channel.description,
          importance: Importance.high,
          priority: Priority.high,
        ),
        iOS: const DarwinNotificationDetails(),
      ),
      payload: message.data['route'],
    );
  }

  static void _handlePayload(String? payload) {
    if (payload == null) return;
    // router.go(payload) via un global navigator key
  }

  static Future<void> _registerToken(String token) async {
    try {
      final platform = Platform.isIOS ? 'ios' : 'android';
      await ApiClient.dio.post('/api/v1/notifications/push/register', data: {
        'device_token': token,
        'platform': platform,
        'provider': 'fcm',
      });
    } catch (_) {
      // Ignore
    }
  }

  static Future<void> logout() async {
    try {
      final token = await FirebaseMessaging.instance.getToken();
      if (token != null) {
        // À terme : DELETE /api/v1/notifications/push/{token}
      }
      await FirebaseMessaging.instance.deleteToken();
    } catch (_) {}
  }
}
