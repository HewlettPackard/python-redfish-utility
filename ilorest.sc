# Copyright 2021-2022 VMware, Inc.
# All rights reserved.

"""Build definition for the sample esxcli plugin

When developing a Daemon for release through the async program:
 * Adjust the copyright message above as appropriate for
   your company
 * set "vendor" to the name of your company
 * set "license" to one of the VMK_MODULE_LICENSE_* strings if applicable;
   otherwise, set it to a 1-word description of your module"s license
 * set "vendor_code" to your company"s VMware-assigned Vendor Code
 * set "solution_id" to your VMWare approved solution id.
 * set "vendor_email" to the contact e-mail provided by your company
 * increment the version number if the source has come from VMware
 * remove "version_bump" if present

When bringing an async daemon inbox at VMware:
 * leave "version" as is from the async release
 * set "version_bump" to 1
 * set "license" to VMK_MODULE_LICENSE_VMWARE (unquoted)
 * set "vendor" to "VMware, Inc."
 * set "vendor_code" to "VMW"
 * set "vendor_email" to the VMware contact e-mail address

If updating the daemon at VMware:
 * increment "version bump" or contact the partner for a new version number

If updating the daemon at an async vendor:
 * increment the version number (do not use version_bump)
"""

#
# identification section
#
ilorestIdentification = {
   "module type"        : "ESXi daemon",
   "binary compat"      : "yes",
   "summary"            : "ilorest tool",
   "description"        : "Restful Interface Tool",
   "version"            : "800.6.1.0.0",
   "license"            : "ThirdParty:Other",
   "vendor"             : "HPE",
   "vendor_code"        : "HPE",
   "solution_id"        : "ilorest",
   "vendor_email"       : "nobody@example.com",
   "componentName"      : "ilorest-component",
   "componentUIName"    : "Restful Interface Tool",
   "componentVersion"   : "800.6.1.0.88-1OEM.802.0.0.22380479",
   "componentUIVersion" : "800.6.1.0.88-1OEM.802.0.0.22380479"
}

#
# Config properties for the ilorest sample
#
ilorestConfigDef = {
   "identification"  : ilorestIdentification,
   "DAEMON version"  : "1.0",
   "configuration"   : "ilorestSolutionConfig.json"
}

ilorestDefinition = {
   "config"                     : ilorestConfigDef,
  "schema version"             : "1.0",
   "component uri"              : "com.example",
   "vital files"                : ["AppToken.dat"],
}
ilorestVital = defineVitalSchema(ilorestDefinition)

#
# Import Chif Library
#
importedLibrary = importLibrary(
                           "lib64/libilorestchif.so",
                           ilorestConfigDef)

ilorestDataDef = {
   "data files"      : ["scripts.tar.gz", "AppToken.dat"],
}
ilorestData = defineDataFiles(ilorestDataDef, ilorestConfigDef)

#
# Definition for the ilorest esxcli plugin
#
ilorestPluginDef = {
   "config"                : ilorestConfigDef,
   "extension definition"  : "ilorest-esxcli.xml",
}
ilorestPlugin = defineEsxcliPlugin(ilorestPluginDef)

# 
# Define a shell script
#
initScriptDef = {
	  "name"       : "ilorest.sh",
	  "script"     : "ilorest.sh",
   	  "config"     : ilorestConfigDef,
}
initScript = defineScript(initScriptDef)

#
ilorestConfig = defineSolutionConfig(ilorestConfigDef, [])

#
# VIB definition for the ilorest esxcli plugin
#
ilorestVibDef = {
   'identification'   : ilorestIdentification,
   'payload'          : [initScript, ilorestPlugin, ilorestData, importedLibrary, ilorestConfig],
   'vib properties'  : {
   "stateless-ready":'true',
   'live-install-allowed':'false',
   'live-remove-allowed':'false',
   'overlay':'false',
      'provides'                : [],
      'depends'                 : [],
      'conflicts'               : [],
      'replaces'                : [],
      'acceptance-level'        : 'accepted',
   }
}

# {"name": "esx-version", "relation": ">=", "version": "8.0.0"},
# {"name": "esx-version", "relation": "<<", "version": "10.0.0"},

ilorestVib = defineDaemonVib(ilorestVibDef, ilorestIdentification, schema=ilorestVital)
#ilorestVib = defineDaemonVib(ilorestVibDef, ilorestIdentification)

#
# Component definition for the ilorest esxcli plugin
#
ilorestBulletinDef = {
   "identification" : ilorestIdentification,
   "vibs"           : [ilorestVib],
   "bulletin" : {
      # These elements show the default values for the corresponding items
      # in bulletin.xml file.  Uncomment a line if you need to use a
      # different value.
      #"severity"    : "general",
      #"category"    : "enhancement",
      #"releaseType" : "extension",
      #"urgency"     : "important",
      #"kbUrl"       : "http://www.example.com",
      "kbUrl"       : "http://www.hpe.com",
      # 1. At least one target platform needs to be specified with
      #    "productLineID"
      # 2. The product version number may be specified explicitly, like 7.8.9,
      #    or, when it"s None or skipped, be a default one for the devkit
      # 3. "locale" element is optional
      "platforms"   : [ {"productLineID":"embeddedEsx"},
                      ]
   }
}
defineComponent(ilorestBulletinDef)
