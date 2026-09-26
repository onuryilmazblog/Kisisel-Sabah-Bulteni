---
title: In development - Microsoft Intune
description: This article describes Microsoft Intune features that are in development.
ms.date: 09/01/2026
ms.topic: whats-new
ai-usage: ai-assisted
ms.reviewer: intuner
ms.collection:
- M365-identity-device-management
---

# In development for Microsoft Intune

To help in your readiness and planning, this article lists Intune UI updates and features that are in development but not yet released. Also:

- If we anticipate that you need to take action before a change, we'll publish a complementary post in the Office message center.
- When a feature enters production, whether it's in preview or generally available, the feature description moves from this article to [What's new](index.md).
- Refer to the [Microsoft 365 roadmap](https://www.microsoft.com/microsoft-365/roadmap?rtc=2&filters=EMS) for strategic deliverables and timelines.

This article and the [What's new](index.md) article are updated periodically. Check back for more updates.

> [!NOTE]
> This article reflects our current expectations about Intune capabilities in an upcoming release. Dates and individual features might change. This article doesn't describe all features in development. It was last updated on the date shown under the title.

You can use RSS to be notified when this article is updated. For more information, see [How to use the docs](../fundamentals/use-docs.md#notifications).
<!-- **RSS feed**: Find out when this article is updated by copying and pasting the following URL into your feed reader: `https://learn.microsoft.com/api/search/rss?search=%22in+development+-+microsoft+intune%22&locale=en-us` -->

<!-- Common categories: use this order:
## Microsoft Intune Suite
## App management
## Device configuration
## Device enrollment
## Device management
## Device security
## Intune apps
## Monitor and troubleshoot
## Role-based access control
## Tenant administration
## Notices
-->

<!-- ***********************************************-->

## Microsoft Intune Suite

### Scope tags support for Endpoint Privilege Management reports<!-- 34639681 -->

We're fixing how scope tags work with Endpoint Privilege Management (EPM) reports. With this change, EPM reports will respect the report viewer's assigned scope and display the details for only the users and devices that the report user is scoped to view.  

<!-- ***********************************************-->

## App management

### Require Managed Home Screen authentication for protected app activities<!-- 35765469 -->

For Android Enterprise dedicated devices using Managed Home Screen (MHS) with Microsoft Entra shared device mode, Intune will allow admins to requiring users to complete MHS authentication state before allowing protected activities in MAM-integrated apps. When MHS requires sign-in or session PIN authentication, users will still be able to complete limited actions, such as accepting or declining incoming calls. If a user tries to open another protected activity, the app will return them to MHS to authenticate. After authentication, protected app activities will become available normally. This behavior will help prevent users from bypassing the MHS session PIN while preserving critical communication actions.

> [!div class="checklist"]
> Applies to:
>
> - Android Enterprise corporate-owned dedicated devices using Managed Home Screen with Microsoft Entra shared device mode

### Declarative VPP app download in Company Portal<!-- 30483698 -->

The iOS/iPadOS Company Portal will support Declarative Volume-Purchased Program (VPP) app downloads from the Apps tab. Declarative VPP apps provide an improved end-user experience by reducing app installation latency, allowing for automatic overnight app updates, and providing the end user with a live status of an app installation. If you choose not to use Declarative VPP apps, there will be no changes to the admin and user experience.

> [!div class="checklist"]
> Applies to:
>
> - iOS/iPadOS

<!-- *********************************************** -->

## Device configuration

### New Apple settings in the Settings Catalog for iOS/iPadOS and macOS<!-- 39430305 -->

Microsoft Intune will add new Apple settings for supported iOS/iPadOS and macOS devices. You'll be able to configure the new options by using Settings Catalog profiles in the Microsoft Intune admin center. These settings will expand the device management controls available through Intune and help you manage Apple devices with a consistent policy workflow. To see these settings, go to **Devices** > **Manage devices** > **Configuration** > **Create** > **New policy** > **iOS/iPadOS** or **macOS** for platform > **Settings catalog** for profile type.

> [!div class="checklist"]
> Applies to:
>
> - iOS/iPadOS
> - macOS

### Enforce Routes capability in iOS/iPadOS and macOS VPN profiles<!-- 28869584 -->

Microsoft Intune will support Apple's **[Enforce Routes](https://developer.apple.com/documentation/networkextension/nevpnprotocol/enforceroutes)** feature in iOS/iPadOS and macOS VPN profiles.

This feature helps prevent situations where VPN traffic accidentally or maliciously goes outside the VPN tunnel, like what happens with de-cloaking risks. It ensures VPN routing aligns with Apple's platform semantics.

When you configure this feature in Intune, routing behavior is defined using **Include all networks** and **Exclude local networks** settings. Intune automatically derives the appropriate **Enforce Routes** configuration based on these selections to ensure consistent and predictable device behavior.

To learn more about VPN profiles in Intune, see:

- [Create VPN profiles to connect to VPN servers in Intune](../device-configuration/templates/configure-vpn.md)
- [Add VPN settings to Apple devices in Microsoft Intune](../device-configuration/templates/ref-vpn-settings-apple.md)

> [!div class="checklist"]
> Applies to:
>
> - iOS/iPadOS
> - macOS

### Disable MAC address randomization on macOS Wi-Fi profiles<!-- 8457343 -->

On macOS devices, the **Disable MAC address randomization** setting will be available for Wi-Fi profiles. Use this setting to disable MAC address randomization on managed macOS devices.

When connecting to a network, devices can present a randomized MAC address instead of the physical MAC address. Using randomized MAC addresses is recommended for privacy, as it's harder to track a device by its MAC address. However, randomized MAC addresses break functionality that relies on a static MAC address, including network access control (NAC).

For more information, see:

- [Wi-Fi profile settings for Apple devices](../device-configuration/templates/ref-wifi-settings-apple.md)
- [Add and use Wi-Fi settings on your devices in Microsoft Intune](../device-configuration/templates/configure-wifi.md)

> [!div class="checklist"]
> Applies to:
>
> - macOS 15 and later

<!-- *********************************************** -->  

<!-- *********************************************** -->

## Device enrollment

### Automatically launch Microsoft Defender for Endpoint during Android Enterprise device setup<!-- 38079776 -->

You'll be able to configure Microsoft Defender for Endpoint to open automatically during out-of-box setup for supported corporate-owned Android Enterprise devices. After you configure the Defender for Endpoint connector, turn on **Grant MTD role permissions**, and assign the Defender app as required, you'll enable this experience from **Endpoint security** > **Defender for Endpoint**. Intune will open Defender during enrollment so users can complete its initial configuration as part of device setup. If configuration isn't completed, the Intune setup step will remain available so users can open Defender again. This experience will help ensure that Defender is configured before enrollment finishes.

> [!div class="checklist"]
> Applies to:
>
> - Android Enterprise corporate-owned fully managed devices (COBO)
> - Android Enterprise corporate-owned devices with a work profile (COPE)

<!-- *********************************************** -->

## Device management

