:global mikrowarpNativeAvailable do={
    :local make [:parse (":return " . $network)]
    :local subnet [$make]
    :local ip [:toip [:pick $network 0 [:find $network "/"]]]
    :foreach address in=[/ip/address/print as-value] do={
        :if (($address->"interface") != "mikrowarp-link") do={
            :local otherMake [:parse (":return " . ($address->"address"))]
            :if (($ip in [$otherMake]) || (($address->"network") in $subnet)) do={ :return false }
        }
    }
    :foreach route in=[/ip/route/print as-value] do={
        :local dst [:tostr ($route->"dst-address")]
        :if (($dst != "0.0.0.0/0") && !((($route->"gateway") = "mikrowarp-link") && ($dst = $network))) do={
            :local otherMake [:parse (":return " . $dst)]
            :local otherIp [:toip [:pick $dst 0 [:find $dst "/"]]]
            :if (($ip in [$otherMake]) || ($otherIp in $subnet)) do={ :return false }
        }
    }
    :return true
}
:global mikrowarpNativeNetwork do={
    :global mikrowarpNativeConfig; :global mikrowarpNativeEnsure; :global mikrowarpNativeComment; :global mikrowarpNativeQuote
    :local c $mikrowarpNativeConfig
    $mikrowarpNativeEnsure menu="/interface/bridge" selector=("name=\"mikrowarp-link\"") properties=({"name"="mikrowarp-link";"protocol-mode"="none";"comment"=[$mikrowarpNativeComment purpose="Transit link"]})
    $mikrowarpNativeEnsure menu="/interface/veth" selector=("name=\"mikrowarp-veth\"") properties=({"name"="mikrowarp-veth";"address"=(($c->"gateway") . "/30");"gateway"=($c->"router");"comment"=[$mikrowarpNativeComment purpose="Gateway"]})
    $mikrowarpNativeEnsure menu="/interface/bridge/port" selector=("interface=\"mikrowarp-veth\"") properties=({"bridge"="mikrowarp-link";"interface"="mikrowarp-veth";"comment"=[$mikrowarpNativeComment purpose="Gateway port"]})
    :local addressComment [$mikrowarpNativeComment purpose="Transit address"]
    $mikrowarpNativeEnsure menu="/ip/address" selector=("comment=" . [$mikrowarpNativeQuote value=$addressComment]) properties=({"address"=(($c->"router") . "/30");"interface"="mikrowarp-link";"comment"=$addressComment})
    :local rules {
        {"menu"="/ip/firewall/nat";"purpose"="Uplink NAT";"properties"={"chain"="srcnat";"src-address"=(($c->"gateway") . "/32");"out-interface"=($c->"uplink");"action"="masquerade"}};
        {"menu"="/ip/firewall/filter";"purpose"="Protect router services";"properties"={"chain"="input";"in-interface"="mikrowarp-link";"connection-state"="invalid,new,untracked";"action"="drop"}};
        {"menu"="/ip/firewall/filter";"purpose"="Allow container uplink";"properties"={"chain"="forward";"in-interface"="mikrowarp-link";"src-address"=(($c->"gateway") . "/32");"out-interface"=($c->"uplink");"action"="accept"}};
        {"menu"="/ip/firewall/filter";"purpose"="Block container initiated LAN access";"properties"={"chain"="forward";"in-interface"="mikrowarp-link";"connection-state"="invalid,new,untracked";"action"="drop"}}
    }
    :local filters [:toarray ""]; :local nat ""
    :foreach rule in=$rules do={
        :local comment [$mikrowarpNativeComment purpose=($rule->"purpose")]
        :local properties ($rule->"properties"); :set ($properties->"comment") $comment
        :local id [$mikrowarpNativeEnsure menu=($rule->"menu") selector=("comment=" . [$mikrowarpNativeQuote value=$comment]) properties=$properties]
        :if (($rule->"menu") = "/ip/firewall/filter") do={ :set filters ($filters,$id) } else={ :set nat $id }
    }
    :if ([:pick [/ip/firewall/nat/find] 0] != $nat) do={ /ip/firewall/nat/move $nat destination=0 }
    :local actual [/ip/firewall/filter/find]
    :if ([:pick $actual 0 3] != $filters) do={ :for i from=2 to=0 step=-1 do={ /ip/firewall/filter/move [:pick $filters $i] destination=0 } }
    $mikrowarpNativeEnsure menu="/container/envs" selector=("list=\"mikrowarp\" and key=\"MIKROWARP_STATE_ID\"") properties=({"list"="mikrowarp";"key"="MIKROWARP_STATE_ID";"value"=($c->"owner")})
    $mikrowarpNativeEnsure menu="/container/mounts" selector=("list=\"mikrowarp\"") properties=({"list"="mikrowarp";"src"=(($c->"directory") . "/data");"dst"="/var/lib/mikrowarp"})
}
:global mikrowarpNativeMain do={
    :global mikrowarpNativeConfig; :global mikrowarpNativeState; :global mikrowarpNativeRelease; :global mikrowarpNativeInput
    :global mikrowarpNativeRead; :global mikrowarpNativeWrite; :global mikrowarpNativeLog; :global mikrowarpNativeChecksum; :global mikrowarpNativeMkdir; :global mikrowarpNativeAvailable; :global mikrowarpNativeNetwork; :global mikrowarpNativeRecordCheck
    :global mikrowarpNativeComment; :global mikrowarpNativeSave; :global mikrowarpNativeResume; :global mikrowarpNativeAbort; :global mikrowarpNativeContainer; :global mikrowarpNativeShell; :global mikrowarpNativeLive
    :local options ($mikrowarpNativeInput->"options")
    :foreach key,value in=$options do={ :if (($key != "network") && ($key != "directory") && ($key != "uplink")) do={ :error ("Unknown option: " . $key) } }
    :local raw [$mikrowarpNativeRead path="mikrowarp-installation.json"]
    :local fresh ($raw = "")
    :if ($fresh && ($action != "apply")) do={ $mikrowarpNativeLog text="MikroWARP has no native installation on this router."; :return true }
    :if ([:len [/system/package/find where name="container" and disabled=no]] != 1) do={ :error "Install the matching RouterOS container package first" }
    :if (![/system/device-mode/get container]) do={ :error "Enable container device mode first; the installer does not reboot the router" }
    :if ($fresh) do={
        :set mikrowarpNativeConfig {"format"="mikrowarp-native-v1";"owner"=[:rndstr from="0123456789abcdef" length=32]}
        :foreach itemName in={"mikrowarp-link";"mikrowarp-veth"} do={ :if ([:len [/interface/find where name=$itemName]] > 0) do={ :error ("Interface name is occupied: " . $itemName) } }
        :foreach itemName in={"mikrowarp";"mikrowarp-next";"mikrowarp-old"} do={ :if ([:len [/container/find where name=$itemName]] > 0) do={ :error ("Container name is occupied: " . $itemName . "; existing installations are not adopted") } }
        :if (([:len [/container/envs/find where list="mikrowarp"]] > 0) || ([:len [/container/mounts/find where list="mikrowarp"]] > 0)) do={ :error "The mikrowarp environment or mount namespace is occupied" }
        :local uplink ($options->"uplink")
        :if ([:len $uplink] = 0) do={
            :local choices [:toarray ""]
            :foreach route in=[/routing/route/print as-value where dst-address="0.0.0.0/0" and routing-table=main and active] do={
                :local gateway [:tostr ($route->"immediate-gw")]
                :if (([:typeof [:find $gateway ","]] != "nil") || ([:typeof [:find $gateway ";"]] != "nil")) do={ :error "Multiple active uplinks; set mikrowarpOptions uplink explicitly" }
                :local mark [:find $gateway "%"]
                :local interface $gateway
                :if ([:typeof $mark] != "nil") do={ :set interface [:pick $gateway ($mark + 1) [:len $gateway]] }
                :if (([:len $interface] > 0) && ([:len [/interface/find where name=$interface]] = 1)) do={ :set ($choices->$interface) true }
            }
            :if ([:len $choices] != 1) do={ :error "Cannot choose one active main-table uplink; set mikrowarpOptions uplink explicitly" }
            :foreach itemName,value in=$choices do={ :set uplink $itemName }
        }
        :if ([:len [/interface/find where name=$uplink]] != 1) do={ :error "The selected uplink does not exist" }
        :set ($mikrowarpNativeConfig->"uplink") $uplink
        :local network ($options->"network")
        :if ([:len $network] = 0) do={
            :foreach pool in={172.31.242.0;10.255.242.0;192.168.242.0} do={
                :for i from=0 to=511 do={
                    :if ([:len $network] = 0) do={
                        :local candidate ([:tostr ($pool + ($i * 4))] . "/30")
                        :if ([$mikrowarpNativeAvailable network=$candidate]) do={ :set network $candidate }
                    }
                }
            }
            :if ([:len $network] = 0) do={ :error "No unused transit subnet found; set mikrowarpOptions network to an unused private /30" }
        }
        :if (!($network ~ "^[0-9]+.[0-9]+.[0-9]+.[0-9]+/30\$")) do={ :error "Transit network must be an IPv4 /30" }
        :local ip [:toip [:pick $network 0 [:find $network "/"]]]
        :if (!(($ip in 10.0.0.0/8) || ($ip in 172.16.0.0/12) || ($ip in 192.168.0.0/16)) || (($ip & 0.0.0.3) != 0.0.0.0)) do={ :error "Use an aligned RFC1918 /30 transit network" }
        :if (![$mikrowarpNativeAvailable network=$network]) do={ :error "Transit network overlaps existing addresses or routes" }
        :set ($mikrowarpNativeConfig->"network") $network
        :set ($mikrowarpNativeConfig->"router") [:tostr ($ip + 1)]
        :set ($mikrowarpNativeConfig->"gateway") [:tostr ($ip + 2)]
        :local need (($mikrowarpNativeRelease->"archive_bytes") + (2 * ($mikrowarpNativeRelease->"logical_bytes")) + 268435456)
        :local directory ($options->"directory")
        :local mount ""
        :if ([:len $directory] = 0) do={
            :if ([/system/resource/get free-hdd-space] >= $need) do={ :set directory "mikrowarp" } else={
                :local most 0
                :foreach disk in=[/disk/print as-value] do={
                    :local point ($disk->"mount-point")
                    :local free ($disk->"free")
                    :if (([:len $point] > 0) && (($disk->"fs") != "tmpfs") && ($free >= $need) && ($free > $most)) do={
                        :local probe ($point . "/mikrowarp-storage-probe.txt")
                        :local writable false
                        :do {
                            :local id [/file/find where name=$probe]
                            :if ([:len $id] > 0) do={ :if ([/file/get $id contents] != "mikrowarp-storage-probe-v1") do={ :error "Probe path occupied" }; /file/remove $id }
                            /file/add name=$probe type=file contents="mikrowarp-storage-probe-v1"
                            :set writable ([/file/get [find where name=$probe] contents] = "mikrowarp-storage-probe-v1")
                            /file/remove [find where name=$probe]
                        } on-error={}
                        :if ($writable) do={ :set directory ($point . "/mikrowarp"); :set mount $point; :set most $free }
                    }
                }
                :if ([:len $directory] = 0) do={ :error ("Not enough writable storage; need " . $need . " free bytes internally or on a mounted disk") }
            }
        }
        :if (!($directory ~ "^[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*\$")) do={ :error "Use a simple relative storage directory such as disk1/mikrowarp" }
        :foreach disk in=[/disk/print as-value] do={
            :local point ($disk->"mount-point")
            :if (([:len $point] > 0) && ([:pick $directory 0 ([:len $point] + 1)] = ($point . "/"))) do={
                :if (($disk->"fs") = "tmpfs") do={ :error "Use persistent storage, not a RAM disk" }
                :set mount $point
            }
        }
        :if ([:len [/file/find where name=$directory]] > 0) do={ :error "Storage directory already exists; choose an unused directory" }
        :set ($mikrowarpNativeConfig->"directory") $directory
        :set ($mikrowarpNativeConfig->"mount") $mount
        :global mikrowarpNativeSpace
        :if ([$mikrowarpNativeSpace] < $need) do={ :error "Selected directory does not have enough staging space" }
        $mikrowarpNativeWrite path="mikrowarp-installation.json" text=[:serialize to=json value=$mikrowarpNativeConfig options=json.no-string-conversion]
        # RouterOS can defer internal file writes for up to 40 seconds. Publish
        # the ownership pointer durably before creating anything on another disk.
        $mikrowarpNativeLog text="Saving installation identity before creating router objects (45 seconds)."
        :delay 45s
    } else={ :set mikrowarpNativeConfig [:deserialize from=json value=$raw options=json.no-string-conversion] }
    :local c $mikrowarpNativeConfig
    :if (($c->"format") != "mikrowarp-native-v1") do={ :error "Unknown installation metadata; nothing is adopted automatically" }
    :if (([:len ($c->"owner")] != 32) || !(($c->"owner") ~ "^[0-9a-f]+\$")) do={ :error "Invalid installation ownership record" }
    :if (!(($c->"directory") ~ "^[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*\$")) do={ :error "Invalid installation directory" }
    :local net ($c->"network")
    :local addr [:toip [:pick $net 0 [:find $net "/"]]]
    :if (([:typeof $addr] != "ip") || ($net != ([:tostr $addr] . "/30"))) do={ :error "Invalid saved transit network" }
    :if (!(($addr in 10.0.0.0/8) || ($addr in 172.16.0.0/12) || ($addr in 192.168.0.0/16)) || (($addr & 0.0.0.3) != 0.0.0.0)) do={ :error "Invalid saved private transit network" }
    :if ((($c->"router") != [:tostr ($addr + 1)]) || (($c->"gateway") != [:tostr ($addr + 2)])) do={ :error "Saved transit addresses differ from the network" }
    :if ([:len [/interface/find where name=($c->"uplink")]] != 1) do={ :error "The saved uplink is missing" }
    :foreach key,value in=$options do={ :if ([:tostr ($c->$key)] != [:tostr $value]) do={ :error ("Saved " . $key . " differs; installation settings are not changed by re-import") } }
    :if ([:len ($c->"mount")] > 0) do={
        :if (([:len [/disk/find where mount-point=($c->"mount") and mounted]] = 0) || ([:pick ($c->"directory") 0 ([:len ($c->"mount")] + 1)] != (($c->"mount") . "/"))) do={ :error "The installation disk is not mounted at its saved location" }
    }
    :local base ($c->"directory")
    :local owner [$mikrowarpNativeRead path=($base . "/owner.txt")]
    :if (($owner != "") && ($owner != ($c->"owner"))) do={ :error "Storage ownership differs" }
    :if ($owner = "") do={
        :foreach f in=[/file/print as-value] do={ :if ([:pick ($f->"name") 0 ([:len $base] + 1)] = ($base . "/")) do={ :error "Unowned files exist in the selected directory" } }
        $mikrowarpNativeMkdir path=$base
        $mikrowarpNativeWrite path=($base . "/owner.txt") text=($c->"owner")
        $mikrowarpNativeLog text="Saving storage ownership (45 seconds)."
        :delay 45s
    }
    # A reboot can interrupt a shell-result handoff. These reserved temporary
    # files are safe to remove only after validating storage ownership and lock.
    :local resultPrefix ($base . "/data/router-result-")
    :foreach f in=[/file/print as-value] do={
        :local filename ($f->"name")
        :if ([:pick $filename 0 [:len $resultPrefix]] = $resultPrefix) do={
            :local tail [:pick $filename [:len $resultPrefix] [:len $filename]]
            :if ((([:len $tail] = 36) || ([:len $tail] = 40)) && ($tail ~ "^[0-9a-f]+[.]txt([.]out)?\$")) do={ /file/remove ($f->".id") }
        }
    }
    :set mikrowarpNativeState [:toarray ""]
    :local invalid 0
    :for slot from=0 to=1 do={
        :local text [$mikrowarpNativeRead path=($base . "/data/installer/operation." . $slot . ".json")]
        :if ([:len $text] > 0) do={
            :do {
                :local envelope [:deserialize from=json value=$text options=json.no-string-conversion]
                :local payload ($envelope->"payload")
                :if ((($envelope->"format") != "mikrowarp-journal-v1") || ([$mikrowarpNativeChecksum text=$payload] != ($envelope->"checksum"))) do={ :error "Invalid journal slot" }
                :local record [:deserialize from=json value=$payload options=json.no-string-conversion]
                :if ((($record->"format") != "mikrowarp-operation-v1") || (($record->"owner") != ($c->"owner"))) do={ :error "Journal owner differs" }
                $mikrowarpNativeRecordCheck record=$record
                :if (([:len $mikrowarpNativeState] = 0) || (($record->"sequence") > ($mikrowarpNativeState->"sequence"))) do={ :set mikrowarpNativeState $record }
            } on-error={ :set invalid ($invalid + 1) }
        }
    }
    :if (([:len $mikrowarpNativeState] = 0) && ($invalid > 0)) do={ :error "No valid operation journal; existing state was preserved" }
    :if ([:len $mikrowarpNativeState] = 0) do={ :set mikrowarpNativeState {"format"="mikrowarp-operation-v1";"owner"=($c->"owner");"sequence"=0;"phase"="empty";"current"=[:toarray ""];"previous"=[:toarray ""]} }
    :if ($action = "status") do={
        $mikrowarpNativeLog text=("Gateway " . ($c->"gateway") . "; operation " . ($mikrowarpNativeState->"phase"))
        :if ([$mikrowarpNativeLive itemName="mikrowarp"]) do={ :local status [$mikrowarpNativeShell itemName="mikrowarp" command="/usr/local/sbin/mikrowarp"]; $mikrowarpNativeLog text=($status->"output") } else={ $mikrowarpNativeLog text="Container is not running." }
        :return true
    }
    :local phase ($mikrowarpNativeState->"phase")
    :local pending (($phase != "empty") && ($phase != "complete") && ($phase != "aborted"))
    :if ($action = "abort") do={ :if ($pending) do={ $mikrowarpNativeAbort } else={ $mikrowarpNativeLog text="No pending operation." }; :return true }
    :if ($pending && ($action = "rollback")) do={ :error "An operation is pending; re-import to resume or select abort first" }
    :if (!$pending) do={
        :local current ($mikrowarpNativeState->"current")
        :local target $mikrowarpNativeRelease
        :local kind "update"; :local restore ""
        :if ($action = "rollback") do={
            :local previous ($mikrowarpNativeState->"previous")
            :if ([:len ($previous->"snapshot")] = 0) do={ :error "No previous accepted image and state are available" }
            :set target ($previous->"bundle"); :set restore ($previous->"snapshot"); :set kind "rollback"
        }
        :if ([:len ($current->"image_id")] = 0) do={ :set kind "install" } else={
            :local id [$mikrowarpNativeContainer itemName="mikrowarp" bundle=$current]
            :if (($id = "") || ([/container/get $id image-id] != ($current->"image_id"))) do={ :error "Current container differs from the saved installation" }
            :if (($target->"image_id") = ($current->"image_id")) do={
                $mikrowarpNativeLog text=("Already installed. Gateway " . ($c->"gateway") . ". No restart or routing changes.")
                :if ([$mikrowarpNativeLive itemName="mikrowarp"]) do={ :local status [$mikrowarpNativeShell itemName="mikrowarp" command="/usr/local/sbin/mikrowarp"]; $mikrowarpNativeLog text=($status->"output") }
                :return true
            }
            :if ([:len [/file/find where name=($base . "/archives/" . ($current->"sha256") . ".tar.gz")]] = 0) do={ :error "Current image archive is missing; update cannot preserve rollback" }
        }
        :if (([:len [/container/find where name="mikrowarp-next"]] > 0) || ([:len [/container/find where name="mikrowarp-old"]] > 0)) do={ :error "A staging container name is already occupied" }
        :set ($mikrowarpNativeState->"kind") $kind
        :set ($mikrowarpNativeState->"old") $current
        :set ($mikrowarpNativeState->"new") $target
        :set ($mikrowarpNativeState->"formerPrevious") ($mikrowarpNativeState->"previous")
        :set ($mikrowarpNativeState->"snapshot") [:rndstr from="0123456789abcdef" length=64]
        :set ($mikrowarpNativeState->"restore") $restore
        :set ($mikrowarpNativeState->"snapshotCreated") false
        $mikrowarpNativeSave phase="staging"
    }
    :if (![$mikrowarpNativeAvailable network=($c->"network")]) do={ :error "The saved transit subnet now conflicts with another address or route" }
    $mikrowarpNativeMkdir path=($base . "/data")
    $mikrowarpNativeWrite path=($base . "/data/owner.txt") text=($c->"owner")
    :foreach directory in={"state";"logs";"diagnostics"} do={ $mikrowarpNativeMkdir path=($base . "/data/" . $directory) }
    $mikrowarpNativeNetwork
    $mikrowarpNativeLog text=("Using " . $base . "; uplink " . ($c->"uplink") . "; gateway " . ($c->"gateway"))
    $mikrowarpNativeResume
    $mikrowarpNativeLog text=("Ready. Gateway " . ($c->"gateway") . ". Traffic selection remains yours.")
}
