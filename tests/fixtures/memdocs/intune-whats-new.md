---
title: What's new in Microsoft Intune
description: Find out what's new in Microsoft Intune.
ms.date: 08/26/2026
ms.topic: whats-new
ai-usage: ai-assisted
ms.custom: msecd-doc-authoring-1023
ms.collection:
- M365-identity-device-management
#customer intent: As an IT administrator, I want to learn what's new in Microsoft Intune so that I can evaluate and use new features.
---

# What's new in Microsoft Intune

Learn what's new each week in Microsoft Intune.

You can also read:

- [**Important notices**](#notices)
- [Past releases](archive.md) in the What's new archive
- Information about [how Intune service updates are released](../fundamentals/servicing-information.md)

> [!NOTE]
> Each monthly [service update](../fundamentals/servicing-information.md) is rolled out gradually to help ensure quality and reliability. Updates are first validated in Microsoft internal environments, then to a small set of customer datacenters before expanding worldwide over the course of several days to a week. Some tenants might see changes before other tenants. The rollout is carefully monitored and might be paused or delayed to protect customers, which can affect timing.
>
> Some features may gradually roll out over several weeks.
>
> For a list of upcoming Intune feature releases, see [In development for Microsoft Intune](./in-development.md).
>
> For new information about Windows Autopilot solutions, see:
>
> - [Windows Autopilot device preparation: What's new](/autopilot/device-preparation/whats-new)
> - [Windows Autopilot: What's new](/autopilot/whats-new)

You can use RSS to be notified when this page is updated. For more information, see [How to use the docs](../fundamentals/use-docs.md#notifications).
<!-- **RSS feed**: Get notified when this page is updated by copying and pasting the following URL into your feed reader: `https://learn.microsoft.com/api/search/rss?search=%22What%27s+new+in+microsoft+intune%3F+-+Azure%22&locale=en-us` -->

<!-- Common categories - in this order:

### Advanced capabilities (formerly "Microsoft Intune Suite")
### App management
### Device configuration
### Device enrollment
### Device management
### Device security
### Intune apps
### Monitor and troubleshoot
### Role-based access control
### Scripts
### Tenant administration

-->  

## Week of August 25, 2026 (Service release 2608)

### Advanced capabilities (formerly "Microsoft Intune Suite")

#### Unattended Remote Help sessions for Windows devices<!-- 9052232 -->

Microsoft Intune now supports unattended Remote Help sessions on physical Windows devices. Authorized helpdesk agents can sign in to a remote device with their own credentials without requiring the user to be present or take action. Helpers can view and control the device to troubleshoot issues and complete support tasks remotely.

For more information, see [Planning for Remote Help](../remote-help/plan.md).

> [!div class="checklist"]
> Applies to:
>
> - Windows

### App management

#### Newly available protected apps for Intune<!-- 37759185, 37775055, 38439465, 38470930, 38472151, 38542841, 38657260 -->

The following protected apps are now available for Microsoft Intune:

- Notion by Notion Labs
- Superhuman Mail by Superhuman Labs
- Calven by Calven Pty Limited
- Heijmans by Heijmans
- Notability by Ginger Labs, Inc. (iOS)
- Ben for Intune by Thanks Ben Ltd
- SDP - On Premises | Intune by Zoho Corporation

For more information about protected apps, see [Microsoft Intune protected apps](../app-management/ref-protected-apps.md).

#### Declarative Device Management for Apple volume purchase program apps<!-- 30457044 -->

Microsoft Intune now supports Apple Declarative Device Management (DDM) for required volume purchase program (VPP) apps on devices running iOS/iPadOS 17.2 and later and macOS 26 and later. By changing the management type to DDM when you upload a new VPP token, you can deploy and configure apps using Apple's policy-based model, which improves delivery efficiency, provides real-time app status, and adds new per-app settings such as automatic app updates.

> [!div class="checklist"]
> Applies to:
>
> - iOS/iPadOS
> - macOS

### Device configuration

#### Configure screen timeout for corporate Android devices<!-- 29677574 -->

Microsoft Intune now supports a **Screen timeout** setting in the Android Enterprise settings catalog, letting you specify how many seconds pass before the screen turns off. Configure it under **Devices** > **Manage devices** > **Configuration** > **Create** > **New policy** > **Android Enterprise** > **Settings catalog**. The value must stay at or below **Time to lock screen** and applies to fully managed and dedicated devices on Android 9 and later, and corporate-owned work profile devices on Android 15 and later.

> [!div class="checklist"]
> Applies to:
>
> - Android Enterprise corporate owned fully managed (COBO)
> - Android Enterprise corporate owned dedicated devices (COSU)
> - Android Enterprise corporate-owned devices with a work profile (COPE)

#### Separate device and work profile passwords on Android Enterprise devices<!-- 31576322 -->

Microsoft Intune now supports the **Block one lock for device and work profile** setting in the Android Enterprise settings catalog, letting you require separate locks for the device and work profile instead of a shared one. Set it to **True** after configuring a work profile password requirement. The default, **False**, allows a common lock. The setting supports Android 9 and later.

> [!div class="checklist"]
> Applies to:
>
> - Android Enterprise corporate-owned devices with a work profile (COPE)

#### Limit how long an Android work profile can stay off<!-- 33982125 -->

Microsoft Intune now supports the **Number of days work profile is allowed to be switched off** setting in the Android Enterprise settings catalog, so you can limit how long a work profile stays turned off. Enter the maximum number of days, with a minimum of three, or enter **0** to disable the restriction. There's no documented upper limit, giving you flexibility for your organization's needs.

> [!div class="checklist"]
> Applies to:
>
> - Android Enterprise corporate-owned devices with a work profile (COPE)

#### Remove eSIMs during a device wipe with a settings catalog policy<!-- 37385796 -->

Microsoft Intune now supports the **Remove all eSIMs during a device wipe** setting in the Android Enterprise settings catalog. Set it to **True** to request removal of all eSIMs when a corporate-owned device is wiped while the policy applies. The default, **False**, doesn't request removal, although the operating system might still remove eSIMs when required. The setting supports Android 15 and later.

> [!div class="checklist"]
> Applies to:
>
> - Android Enterprise corporate owned fully managed (COBO)
> - Android Enterprise corporate owned dedicated devices (COSU)
> - Android Enterprise corporate-owned devices with a work profile (COPE)

#### New updates to the Apple settings catalog<!-- 38356110 -->

Microsoft Intune now supports new Settings Catalog options for testing on the OS 27 betas, covering Declarative Device Management areas such as **App Settings**, **Web Content Filter**, and **Siri Settings** for iOS/iPadOS and macOS. Configure them under **Devices** > **Manage devices** > **Configuration** > **Create** > **New policy** > **iOS/iPadOS** or **macOS** > **Settings catalog**. This lets you test upcoming Apple management controls ahead of general availability.

For more information, see [Create a policy using settings catalog](../device-configuration/settings-catalog/index.md).

> [!div class="checklist"]
> Applies to:
>
> - iOS/iPadOS
> - macOS

#### Keep Android device screens on while charging<!-- 38815189 -->

Microsoft Intune now includes a settings catalog option for keeping fully managed and dedicated Android device screens on while charging. Select one or more modes - **AC**, **USB**, or **Wireless** - to control when the screen stays on. AC and USB support Android 6.0 and later; wireless charging requires Android 8.1 and later. No modes are selected by default.

> [!div class="checklist"]
> Applies to:
>
> - Android Enterprise corporate owned fully managed (COBO)
> - Android Enterprise corporate owned dedicated devices (COSU)

#### New policy settings for Windows<!-- 38928110 -->

Microsoft Intune now includes new Windows settings catalog options across several administrative template refreshes. Highlights include **Turn on Protected Mode** controls for Internet Explorer security zones, new Microsoft Edge policies from the Edge 150 template refresh, and a **Disconnect if a Remote Desktop Services session when no smart card is present** option for interactive logon. The Microsoft Office templates also gained new settings. Create a Windows settings catalog profile to configure them.

> [!div class="checklist"]
> Applies to:
>
> - Windows

### Device enrollment

#### Skip new Apple Setup Assistant panes during enrollment<!-- 38408206 -->

Microsoft Intune now includes Apple OS 27 Setup Assistant skip keys for Liquid Glass and Accessibility Appearance in Automated Device Enrollment profiles. You can hide these panes to reduce setup interactions and provide a more consistent enrollment experience on supported iPhone, iPad, and Mac devices.

> [!div class="checklist"]
> Applies to:
>
> - iOS/iPadOS
> - macOS

### Device management

#### New single device page in the Intune admin center<!-- 16532161 -->

The new single device page is turned on by default for all customers. You can use the **Preview new device view** toggle to turn it off and return to the original device page.

In the Intune admin center, when you go to **Devices** > **All devices** and select a device, you can see device-specific information, including device properties, device activity, tools, and reports.

**Where to find common device information and actions in the new single device view:**

- Change the management name, primary user, or device category: Go to **Devices** > **All devices** > select a device > **Properties** > **Edit**.
- View hardware and operating system information: Go to **Devices** > **All devices** > select a device > **Device details**. The **Device details** tab was previously called **Hardware**.
- Perform device actions: Go to **Devices** > **All devices** and select a device. Some actions are organized in the **Remote actions**, **Secure**, and **Remove data** menus on the device command bar. The available actions depend on the device platform, management type, ownership, permissions, and supported capabilities.
- View the status of device actions: Go to **Devices** > **All devices** > select a device > **Device action status**.
- View the status of Remediations: Go to **Devices** > **All devices** > select a device > **Tools** > **Remediations**.
- View scope tags: Go to **Devices** > **All devices** > select a device > **Properties**.

**Return to the original device page:**

If you prefer to use the original device page, you can turn off the new experience:

1. In the Intune admin center, go to **Devices** > **All devices**.
1. Move the **Preview new device view** toggle to **Off**.

> [!div class="checklist"]
> Applies to:
>
> - Android
> - iOS/iPadOS
> - macOS
> - Windows

#### Operating system version property in assignment filters is generally available<!-- 38448498 -->

The `operatingSystemVersion` property in assignment filters is now generally available for managed devices and managed apps. Use this property to create filter rules that scope your app and policy assignments to devices running a specific OS version or build range. For example, create an assignment filter that pilots a configuration on a newer build before rolling it out broadly or excludes devices that haven't yet updated.

You can build rules using the rule editor or the rule syntax text box, with the same operators available for other filter properties. Existing assignments continue to work without changes.

For more information, see:

- [Use assignment filters to assign apps, policies, and profiles](../fundamentals/filters/overview.md)
- [App and device properties, operators, and rule editing when creating assignment filters](../fundamentals/filters/ref-device-properties.md)

#### Collect enhanced diagnostic logs from supervised Apple devices<!-- 35859652 -->

Microsoft Intune now supports Apple's Enhanced Logging device action on supported supervised devices running a compatible OS release. Administrators can start an AppleCare diagnostic-log collection session using an AppleCare-provided token and monitor device-reported status through Declarative Device Management, reducing the need to coordinate manual log collection with the device user.

> [!div class="checklist"]
> Applies to:
>
> - iOS/iPadOS
> - macOS

> [!NOTE]
> The following eSIM features are rolling out and might not be available to all tenants yet.

#### View expanded SIM inventory for corporate-owned Android devices<!-- 36971225 -->

Microsoft Intune now surfaces expanded SIM inventory for corporate-owned Android Enterprise devices, including EIDs, multiple ICCIDs, and activation state. View these details under **Devices** > **All devices** > select a device > **Hardware**, and use the reported ICCID to identify the correct eSIM for a removal action. EID reporting requires Android 13 and later; full inventory requires Android 15 and later.

> [!div class="checklist"]
> Applies to:
>
> - Android Enterprise corporate owned fully managed (COBO)
> - Android Enterprise corporate owned dedicated devices (COSU)
> - Android Enterprise corporate-owned devices with a work profile (COPE)

#### Activate an eSIM on a corporate-owned Android device<!-- 36971755 -->

Microsoft Intune now supports single-device eSIM activation for corporate-owned Android Enterprise devices running Android 15 and later. Turn on **Preview new device view**, select the device, then select **Activate eSIM** and enter the carrier activation code. Intune sends the request without first blocking it based on reported eSIM slot capacity and surfaces errors returned by Google. Personally owned work profile devices aren't supported.

> [!div class="checklist"]
> Applies to:
>
> - Android Enterprise corporate owned fully managed (COBO)
> - Android Enterprise corporate owned dedicated devices (COSU)
> - Android Enterprise corporate-owned devices with a work profile (COPE)

#### Remove an individual eSIM from a corporate-owned Android device<!-- 36975091 -->

Microsoft Intune now lets you remove a single eSIM from a corporate-owned Android Enterprise device without wiping it. Turn on **Preview new device view**, select the device, copy the eSIM's ICCID from device inventory, then select **Remove eSIM** and enter the ICCID. The action supports fully managed and dedicated devices on Android 15 and later, and work profile devices on Android 17 and later.

> [!div class="checklist"]
> Applies to:
>
> - Android Enterprise corporate owned fully managed (COBO)
> - Android Enterprise corporate owned dedicated devices (COSU)
> - Android Enterprise corporate-owned devices with a work profile (COPE)

#### Choose whether to remove eSIMs when wiping one corporate-owned Android device<!-- 36975226 -->

Microsoft Intune now lets you choose whether to preserve or remove eSIMs when wiping one corporate-owned Android Enterprise device. Turn on **Preview new device view**, select the device, then select **Wipe**. By default, the wipe preserves eSIMs; select the eSIM removal option only when you want the wipe to remove them. Personally owned work profile devices aren't supported.

> [!div class="checklist"]
> Applies to:
>
> - Android Enterprise corporate owned fully managed (COBO)
> - Android Enterprise corporate owned dedicated devices (COSU)
> - Android Enterprise corporate-owned devices with a work profile (COPE)

#### Device inventory for personally owned devices on Android Enterprise<!-- 37853885 -->

Microsoft Intune now supports device inventory for personally owned Android Enterprise devices with a work profile managed by Android Management API. View these devices from the device's **Inventory** page alongside corporate-owned devices in Resource Explorer, and query them with Multi-Device Query. Inventory data is a subset of corporate-owned data; properties such as IMEI, ICCID, and MAC address aren't available. This gives you more consistent analytics across mixed corporate and BYOD environments.

> [!div class="checklist"]
> Applies to:
>
> - Android Enterprise personally owned devices with a work profile using Android Management API

### Device security

#### Audit mode for the Microsoft Defender Antivirus template for Linux<!-- 37284585 -->

The Microsoft Defender Antivirus template for Linux, which is part of Intune's Endpoint Security Antivirus policy, now includes a new **Audit** value for the **Enforcement level** setting. When you set **Enforcement level** to **Audit**, the antivirus engine detects threats in real time but doesn't automatically remediate them. Malware detections are reported as alerts in the Microsoft Defender portal through real-time scanning, without quarantining the malicious files. Audit mode gives you visibility into the threat landscape before you turn on full protection.

The Microsoft Defender Antivirus template for Linux is supported for devices [managed by Intune](../device-configuration/endpoint-security/antivirus.md), and for devices managed only by Defender through the [Microsoft Defender for Endpoint security settings management](../device-security/microsoft-defender/security-settings-management.md) scenario (MDE attach).

> [!div class="checklist"]
> Applies to:
>
> - Linux

#### Windows 365 for Agents security baseline<!-- 37334751 -->

Microsoft Intune now includes a security baseline for Windows 365 for Agents Cloud PCs. Administrators can deploy and customize recommended, device-scoped settings for Windows 11, Microsoft Edge, and Microsoft Defender for Endpoint to establish a consistent security posture for agentic workloads.

For more information, see [Manage security baseline profiles in Microsoft Intune](../device-security/security-baselines/configure-baselines.md) and [What is Windows 365 for Agents?](https://learn.microsoft.com/windows-365/agents/introduction-windows-365-for-agents).

> [!div class="checklist"]
> Applies to:
>
> - Windows 365 for Agents Cloud PCs running Windows 11 and later

#### Memory scan setting for Microsoft Defender Antivirus on Linux<!-- 37379877 -->

Microsoft Intune now supports a memory scan setting in the Microsoft Defender Antivirus template for Linux endpoint security antivirus policies. You can manage memory scan behavior on Linux devices managed through Microsoft Defender for Endpoint security settings management, giving you finer control over how Defender inspects memory on your Linux endpoints.

> [!div class="checklist"]
> Applies to:
>
> - Linux

## Week of July 27, 2026 (Service release 2607)

### Device configuration

#### Samsung Knox E-FOTA firmware update management for Android Enterprise devices<!-- 6515233 -->

Microsoft Intune now integrates with Samsung Knox E-FOTA (Firmware Over-The-Air), so you can manage firmware updates for corporate-owned Samsung devices directly in the Microsoft Intune admin center. Control which firmware version each device receives, deploy updates without user interaction, and schedule downloads and installations to reduce downtime.

For more information, see [Samsung Knox E-FOTA integration with Microsoft Intune](../device-updates/android/setup-samsung-knox.md).

> [!div class="checklist"]
> Applies to:
>
> - Android Enterprise corporate-owned dedicated (COSU)
> - Android Enterprise corporate-owned fully managed (COBO)
> - Android Enterprise corporate-owned with a work profile (COPE)

#### New settings available in the Windows settings catalog<!-- 37759479 -->

Microsoft Intune now includes new settings in the Windows settings catalog for Windows devices. You can configure options for camera behavior, Keyboard Filter controls (for Windows Insider devices), and Windows Subsystem for Linux (WSL). To find them, go to **Devices** > **Manage devices** > **Configuration** > **Create** > **New policy** > **Windows 10 and later** > **Settings catalog**.

> [!div class="checklist"]
> Applies to:
>
> - Windows 11
> - Windows 10

#### New Microsoft Edge settings in the Windows settings catalog<!-- 38140497 -->

The Microsoft Edge administrative templates were refreshed to Microsoft Edge 149 (version 149.0.4022.21), which adds the latest Microsoft Edge 148 and 149 policy settings to the Windows settings catalog. The new settings are:

- **[Allow Local Fonts permission on these sites](/deployedge/microsoft-edge-policies/localfontsallowedforurls)** (LocalFontsAllowedForUrls)
- **[Allow M365 authentication popups in work profiles](/deployedge/microsoft-edge-policies/m365authpopupsinworkenabled)** (M365AuthPopupsInWorkEnabled)
- **[Allow MAM enrollment when managed device has Purview DLP policy configured](/deployedge/microsoft-edge-policies/mamwithdevicedlpenabled)** (MAMWithDeviceDLP)
- **[Automatically open Copilot side pane with contextual insights for links opened from Outlook](/deployedge/microsoft-edge-policies/m365linksautoopencopilotenabled)** (M365LinksAutoOpenCopilotEnabled)
- **[Block Local Fonts permission on these sites](/deployedge/microsoft-edge-policies/localfontsblockedforurls)** (LocalFontsBlockedForUrls)
- **[Browsing with Copilot Allowed URLs](/deployedge/microsoft-edge-policies/browsingwithcopilotallowlist)** (BrowsingWithCopilotAllowList)
- **[Browsing with Copilot Blocked URLs](/deployedge/microsoft-edge-policies/browsingwithcopilotblocklist)** (BrowsingWithCopilotBlockList)
- **[Configure whether the Discover or Work feed tabs are shown on the Copilot new tab page](/deployedge/microsoft-edge-policies/configurentpfeedtabvisibility)** (ConfigureNTPFeedTabVisibility)
- **[Controls the availability of browsing with Copilot in Microsoft Edge](/deployedge/microsoft-edge-policies/allowbrowsingwithcopilot)** (AllowBrowsingWithCopilot)
- **[Default Local Fonts permission setting](/deployedge/microsoft-edge-policies/defaultlocalfontssetting)** (DefaultLocalFontsSetting)
- **[Enable Copilot address bar suggestions](/deployedge/microsoft-edge-policies/copilotaddressbarsuggestionsenabled)** (CopilotAddressBarSuggestionsEnabled)
- **[Enable opaque origins for data URLs in Web Workers](/deployedge/microsoft-edge-policies/dataurlinwebworkeropaqueoriginenabled)** (DataUrlInWebWorkerOpaqueOriginEnabled)
- **[Enable the Copilot new tab page](/deployedge/microsoft-edge-policies/copilotnewtabpageenabled)** (CopilotNewTabPageEnabled)
- **[Enable the extended lifetime option for SharedWorkers](/deployedge/microsoft-edge-policies/sharedworkerextendedlifetimeenabled)** (SharedWorkerExtendedLifetimeEnabled)
- **[Force foreground priority for specific URLs](/deployedge/microsoft-edge-policies/forceforegroundpriorityforurls)** (ForceForegroundPriorityForUrls)
- **[List of URL patterns for which developer tools are allowed to be opened](/deployedge/microsoft-edge-policies/developertoolsavailabilityallowlist)** (DeveloperToolsAvailabilityAllowlist)
- **[List of URL patterns for which developer tools are blocked](/deployedge/microsoft-edge-policies/developertoolsavailabilityblocklist)** (DeveloperToolsAvailabilityBlocklist)
- **[Maximum number of concurrent connections to the proxy server for WebSocket requests](/deployedge/microsoft-edge-policies/maxconnectionsperproxyforwebsocket)** (MaxConnectionsPerProxyForWebSocket)
- **[Override for the CPU performance tier](/deployedge/microsoft-edge-policies/cpuperformancetieroverride)** (CpuPerformanceTierOverride)
- **[Set the default Copilot new tab page feed tab to Work or Discover](/deployedge/microsoft-edge-policies/setntpdefaultfeedtab)** (SetNTPDefaultFeedTab)

For the full list of policies, see the [Microsoft Edge policies reference](/deployedge/microsoft-edge-policies).

> [!div class="checklist"]
> Applies to:
>
> - Windows

#### New Windows App (Azure Virtual Desktop) settings in the Windows settings catalog<!-- 38140497 wndraft wnready -->

 
There are new Windows App settings in the Windows settings catalog. To see and configure them in Intune, create a Windows settings catalog profile (**Devices** > **Manage devices** > **Configuration** > **Create** > **New policy** > **Windows 10 and later** > **Settings catalog**). The new settings are:
- **Turn off automatic updates for Windows App** – controls whether Windows App automatically checks for and installs updates.
- **Automatically log off users after inactive interval** – signs users out of Windows App after a set period of inactivity.
- **Skip First Run Experience (FRE)** – skips the first-run experience so users go straight to their resources.
- **Admin Release Ring Policy** – sets the update release ring (channel) that Windows App follows.
- **Automatically create Windows App shortcuts to desktop** – creates desktop shortcuts for published Windows App resources.
For more information, see [Configure updates for Windows App](/windows-app/configure-updates-windows).
> [!div class="checklist"]
> Applies to:
>
> - Windows

 
#### New option for the Remove Default Microsoft Store packages setting<!-- 38140497 wndraft wnready-->

 
The existing **Remove Default Microsoft Store packages** setting in the ApplicationManagement area has a new subsetting, **Specify additional package family names to remove**. It lets you provide a custom list of package family names (PFNs) to remove, in addition to the built-in default set of Microsoft Store packages.
For more information, see the [ApplicationManagement policy CSP](/windows/client-management/mdm/policy-csp-applicationmanagement).
> [!div class="checklist"]
> Applies to:
>
> - Windows

 
#### New setting to disable the Get Started app<!-- 38140497 wndraft wnready-->

 
The new **Disable Get Started** setting prevents the Windows Get Started app from being available to users.
For more information, see the [Experience policy CSP](/windows/client-management/mdm/policy-csp-experience).
> [!div class="checklist"]
> Applies to:
>
> - Windows

 
#### New OneDrive settings in the Windows settings catalog<!-- 38140497 wndraft wnready-->

 
There are new OneDrive settings in the Windows settings catalog:
- **Set a custom name for the OneDrive folder** – sets a custom name for the synced OneDrive folder on the user's device.
- **Enable OpenID Connect (OIDC) authentication for syncing content from an on-prem SharePoint Server using the OneDrive sync app** – lets the OneDrive sync app authenticate to an on-premises SharePoint Server using OpenID Connect when the server supports it.
- **Specify the Application ID URI for your Entra application for OIDC** – specifies the Application ID URI for your Microsoft Entra application used for OIDC when it differs from your SharePoint Server URL.
- **Prevent users at your organization from enabling offline mode in OneDrive on the web** – blocks users from turning on offline mode for OneDrive on the web.
- **Prevent users at your organization from enabling offline mode in OneDrive on the web for libraries and folders that are shared from other organizations** – blocks offline mode for libraries and folders shared from other organizations.
- **Hard-delete the contents of a folder shortcut when unmounted** – permanently deletes the contents of a folder shortcut when it is unmounted instead of moving them to the Recycle Bin.
- **Hard-delete contents of a folder shortcut when a user loses permissions to the folder** – permanently deletes the contents of a folder shortcut when the user loses permissions to that folder.
For more information, see [Use Group Policy to control OneDrive sync app settings](/sharepoint/use-group-policy).
> [!div class="checklist"]
> Applies to:
>
> - Windows

 
#### Updated Visual Studio administrative templates in the Windows settings catalog<!-- 38140497 wndraft wnready-->

 
The Visual Studio administrative templates were refreshed to version 1.0.184.40051, which adds the latest Visual Studio policy settings to the Windows settings catalog. The new setting is:
- **[Disable Model Context Protocol (MCP)](/visualstudio/ide/visual-studio-github-copilot-admin#configure-copilot-group-policy)** (DisableMCP)
For more information, see the [Visual Studio administrative templates documentation](/visualstudio/install/administrative-templates).
> [!div class="checklist"]
> Applies to:
>
> - Windows

### Device enrollment

#### Skip Setup Assistant screens for tvOS and visionOS enrollment<!-- 37665726 -->

Microsoft Intune now supports hiding or showing new Setup Assistant screens during automated device enrollment (ADE) for tvOS and visionOS devices. When you configure an enrollment profile, you can choose which screens, such as **Apple ID**, **Diagnostics Data**, and **Location Services**, appear during setup. By default, these screens are shown.

For more information, see [Set up ADE for tvOS](../device-enrollment/apple/setup-automated-tv-os.md) and [Set up ADE for visionOS](../device-enrollment/apple/setup-automated-vision-os.md).

> [!div class="checklist"]
> Applies to:
>
> - tvOS
> - visionOS

#### Dedicated RBAC permission for zero-touch enrollment<!-- 29694995 -->

Microsoft Intune now provides a dedicated role-based access control (RBAC) permission for Google zero-touch enrollment portal access. Previously, the zero-touch enrollment iframe in the Microsoft Intune admin center required the **Update app sync** permission, which also grants rights to manage Managed Google Play app sync. With the dedicated permission, you can grant zero-touch enrollment portal access independently from app management permissions.

For more information, see [Enroll by using Google Zero Touch](../device-enrollment/android/ref-corporate-methods.md#enroll-by-using-google-zero-touch).

> [!div class="checklist"]
> Applies to:
>
> - Android Enterprise

### Device management

#### Collect Windows registry data with the properties catalog<!-- 33470861 -->

Microsoft Intune now lets you collect Windows registry data through the properties catalog. When you create a device inventory policy, you can define specific registry keys and values to collect from enrolled Windows devices, including a single value, all values directly under a key, or the same value across subkeys under **HKEY_LOCAL_MACHINE**. This gives you richer device state visibility and advanced querying without custom scripts.

For more information, see [Use the Intune properties catalog to get device hardware properties](../device-configuration/collect-device-properties.md).

> [!div class="checklist"]
> Applies to:
>
> - Windows

#### Improved on-demand device sync for Windows devices<!-- 37533252, 37595192 -->

Microsoft Intune now supports a more comprehensive on-demand sync for Windows devices. When you select the **Sync** device action in the Microsoft Intune admin center, Intune initiates a full synchronization across key workloads, including configuration policies, apps, and scripts, so devices reflect your latest changes faster. This capability is especially useful during troubleshooting, incident response, and high-priority rollouts.

For more information, see [Device action: sync](../device-management/actions/sync.md).

> [!div class="checklist"]
> Applies to:
>
> - Windows

### Device security

#### Custom compliance settings for macOS<!-- 35392462 -->

