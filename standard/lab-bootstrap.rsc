# Only imported after resetting the dedicated local QEMU clone.
/system/identity set name=mikrowarp-standard-lab
:if ([:len [/ip/dhcp-client find where interface=ether1]] = 0) do={ /ip/dhcp-client add interface=ether1 disabled=no use-peer-dns=no }
/ip/dhcp-client set [find where interface=ether1] disabled=no use-peer-dns=no
/ip/dns set servers=1.1.1.1,9.9.9.9 allow-remote-requests=no
/ip/service enable ssh
/ip/service set ssh port=22
:if ([:len [/interface/bridge find where name=lab-lan]] = 0) do={ /interface/bridge add name=lab-lan protocol-mode=none comment="R14 LAB | Client network" }
:if ([:len [/interface/bridge/port find where interface=ether2]] = 0) do={ /interface/bridge/port add bridge=lab-lan interface=ether2 }
:if ([:len [/ip/address find where address="192.168.88.1/24"]] = 0) do={ /ip/address add address=192.168.88.1/24 interface=lab-lan comment="R14 LAB | Client gateway" }
:if ([:len [/ip/firewall/nat find where comment="R14 LAB | Existing administrator WAN NAT"]] = 0) do={ /ip/firewall/nat add chain=srcnat out-interface=ether1 action=masquerade comment="R14 LAB | Existing administrator WAN NAT" }
:put "MIKROWARP-FRESH-LAB-READY"
