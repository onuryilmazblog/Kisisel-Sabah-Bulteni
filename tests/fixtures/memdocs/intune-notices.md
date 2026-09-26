---
ms.topic: include
ms.date: 10/14/2025
---

These notices provide important information that can help you prepare for future Intune changes and features.

### Plan for Change: Intune is moving to support iOS/iPadOS 18 and later

Later in calendar year 2026, we expect iOS 27 and iPadOS 27 to be released by Apple. Microsoft Intune, including the Intune Company Portal and Intune app protection policies (APP, also known as MAM), requires [iOS 17/iPadOS 17 and higher](../../fundamentals/ref-supported-platforms.md) shortly after the iOS/iPadOS 27 release.

#### How does this change affect you or your users?

If you're managing iOS/iPadOS devices, you might have devices that won't be able to upgrade to the minimum supported version (iOS 18/iPadOS 18).

Given that Microsoft 365 mobile apps are supported on iOS 18/iPadOS 18 and higher, this change might not affect you. You likely already upgraded your OS or devices.

To check which devices support iOS 18 or iPadOS 18 (if applicable), see the following Apple documentation:

- [Supported iPhone models](https://support.apple.com/guide/iphone/iphone-models-compatible-with-ios-18-iphe3fa5df43/18.0/ios/18.0)
- [Supported iPad models](https://support.apple.com/guide/ipad/ipad-models-compatible-with-ipados-18-ipad213a25b2/18.0/ipados/18.0)

> [!NOTE]
> Userless iOS and iPadOS devices enrolled through Automated Device Enrollment (ADE) have a slightly nuanced support statement due to their shared usage. The minimum supported OS version changes to iOS 18/iPadOS 18 while the allowed OS version changes to iOS 16/iPadOS 16 and later. For more information, see [this statement about ADE Userless support](https://aka.ms/ADE_userless_support).

#### How can you prepare?

Check your Intune reporting to see what devices or users might be affected. For devices with mobile device management (MDM), go to **Devices** > **All devices** and filter by OS. For devices with app protection policies, go to **Apps** > **Monitor** > **App protection status** and use the *Platform* and *Platform version* columns to filter.

To manage the supported OS version in your organization, you can use Microsoft Intune controls for both MDM and APP. For more information, see [Manage operating system versions with Intune](../../device-updates/manage-os-versions.md).

### Plan for change: Intune is moving to support macOS 15 and higher later this year

Later in calendar year 2026, we expect macOS Golden Gate 27 to be released by Apple. Microsoft Intune, the Company Portal app, and the Intune mobile device management agent support macOS 15 and later. Since the Company Portal app for iOS and macOS are a unified app, this change will occur shortly after the release of macOS 27. This change doesn't affect existing enrolled devices.

#### How does this change affect you or your users?

This change only affects you if you currently manage, or plan to manage, macOS devices with Intune. If your users have likely already upgraded their macOS devices, then this change might not affect you. For a list of supported devices, refer to [macOS Sequoia is compatible with these computers](https://support.apple.com/120282).

> [!NOTE]
> Devices that are currently enrolled on macOS 14.x or below will continue to remain enrolled even when those versions are no longer supported. New devices are unable to enroll if they're running macOS 14.x or below.

#### How can you prepare?

Check your Intune reporting to see what devices or users might be affected. Go to **Devices** > **All devices** and filter by macOS. You can add more columns to help identify who in your organization has devices running macOS 14.x or earlier. Ask your users to upgrade their devices to a supported OS version.

### Warning notifications for iOS apps running unsupported SDK versions

We're continuing improvements to the Microsoft Intune mobile application management (MAM) service to ensure applications remain secure, reliable, and aligned with the latest platform capabilities. 

Starting in late June 2026, users opening iOS apps built with an Intune MAM SDK version earlier than 20.8.0 will see a warning message recommending they update to a supported app version for the best experience and continued compatibility.

#### How does this change affect you or your users?

Users running iOS apps with an Intune MAM SDK version lower than 20.8.0 will see a warning message. The warning will appear in iOS apps such as Microsoft Teams, Outlook, Edge and OneDrive. Note that this notification is non-blocking, users can dismiss the message and continue using the app.

#### How can you prepare?

Notify users to update to the latest versions of Microsoft and third-party apps as soon as possible. The latest versions are available in Apple's [App store](https://www.apple.com/app-store/). For example, you can find the latest version of Microsoft Teams [here](https://apps.apple.com/app/microsoft-teams/id1113153706) and Microsoft Outlook [here](https://apps.apple.com/app/microsoft-outlook/id951937596).

If applicable, notify your helpdesk and support teams about the warning message. Additionally, as an IT admin you can use [Conditional Launch](../../app-management/protection/ref-settings-ios.md#conditional-launch) settings to block unsupported app or SDK versions that are still in use:

- The **Min SDK version** setting to block users if the app is using Intune SDK for iOS older than 20.8.0.
- The **Min app version** setting to warn or block users on older Microsoft apps. Note, this setting must be in a policy targeted to only the targeted app.

### Update to the latest Intune Company Portal for Android, Intune App SDK for iOS, and Intune App Wrapper for iOS

Starting **January 19, 2026**, or soon after, we're making updates to improve the Intune mobile application management (MAM) service. To stay secure and run smoothly, this update will require iOS wrapped apps, iOS SDK integrated apps, and the Intune Company Portal for Android to be updated to the latest versions.

> [!IMPORTANT]
> If you don't update to the latest versions, users will be blocked from launching your app.

The way Android updates, once one Microsoft application with the updated SDK is on the device and the Company Portal is updated to the latest version, Android apps will update, so this message is focused on iOS SDK/app wrapper updates. We recommend to always update your Android and iOS apps to the latest SDK or app wrapper to ensure that your app continues to run smoothly. Review the following GitHub announcements for more details on the specific effect:

- SDK for iOS: [Action Required: Update the MAM SDK in your application to avoid end user impact - microsoftconnect/ms-intune-app-sdk-ios Discussion #598 | GitHub](https://github.com/microsoftconnect/ms-intune-app-sdk-ios/discussions/598)
- Wrapper for iOS: [Action Required: Wrap your application with version 20.8.1+ to avoid end user impact - microsoftconnect/intune-app-wrapping-tool-ios Discussion #143 | GitHub](https://github.com/microsoftconnect/intune-app-wrapping-tool-ios/discussions/143)

If you have questions, leave a comment on the applicable GitHub announcement.  

#### How does this change affect you or your users?

If your users haven't updated to the latest Microsoft or third-party app protection supported apps, they'll be blocked from launching their apps. If you have iOS line-of-business (LOB) applications that are using the Intune wrapper or Intune SDK, you must be on Wrapper/SDK version **20.8.0** or later for apps compiled with Xcode 16 and version **21.1.0** or later for apps compiled with Xcode 26 to avoid your users being blocked. 

#### How can you prepare?

Plan to make the following changes before **January 19, 2026**:

- For apps using the Intune App SDK, you must update to the new version of the Intune App SDK for iOS:  
  - For apps built with XCode 16 use [v20.8.0 - Release 20.8.0 - microsoftconnect/ms-intune-app-sdk-ios | GitHub](https://github.com/microsoftconnect/ms-intune-app-sdk-ios/releases/tag/20.8.0)
  - For apps built with XCode 26 use [v21.1.0 - Release 21.1.0 - microsoftconnect/ms-intune-app-sdk-ios | GitHub](https://github.com/microsoftconnect/ms-intune-app-sdk-ios/releases/tag/21.1.0) 

- For apps using the wrapper, you must update to the new version of the Intune App Wrapping Tool for iOS: 
  - For apps built with XCode 16 use [v20.8.1 - Release 20.8.1 - microsoftconnect/intune-app-wrapping-tool-ios | GitHub](https://github.com/microsoftconnect/intune-app-wrapping-tool-ios/releases/tag/20.8.1)
  - For apps built with XCode 26 use [v21.1.0 - Release 21.1.0 - microsoftconnect/intune-app-wrapping-tool-ios | GitHub](https://github.com/microsoftconnect/intune-app-wrapping-tool-ios/releases/tag/21.1.0)

- For tenants with policies targeted to iOS apps: 
  - Notify your users that they need to upgrade to the latest version of the Microsoft apps. You can find the latest version of the apps in the [App store](https://www.apple.com/app-store/). For example, you can find the latest version of Microsoft Teams [here](https://apps.apple.com/app/microsoft-teams/id1113153706) and Microsoft Outlook [here](https://apps.apple.com/app/microsoft-outlook/id951937596).
  - Additionally, you can enable the following [conditional launch](../../app-management/protection/ref-settings-ios.md#conditional-launch) settings: 
    - The **Min SDK version** setting to block users if the app is using Intune SDK for iOS older than 20.8.0. 
    - The **Min app version** setting to warn users on older Microsoft apps. Note, this setting must be in a policy targeted to only the targeted app. 

- For tenants with policies targeted to Android apps:

  - Notify your users that they need to upgrade to the latest version (v5.0.6726.0) of the [Intune Company Portal](https://play.google.com/store/apps/details?id=com.microsoft.windowsintune.companyportal) app. 
  - Additionally, you can enable the following [conditional launch](../../app-management/protection/ref-settings-ios.md#conditional-launch) device condition setting:

    - The **Min Company Portal version** setting to warn users using a Company Portal app version older than 5.0.6726.0.

> [!NOTE]
> Use Conditional Access policy to ensure that only apps with app protection policies can access corporate resources. For more information, see the [Require approved client apps or app protection policy with mobile devices](/entra/identity/conditional-access/policy-all-users-approved-app-or-app-protection#require-approved-client-apps-or-app-protection-policy-with-mobile-devices) on creating Conditional Access policies.
