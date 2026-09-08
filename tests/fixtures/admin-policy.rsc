# Test fixture only. These are administrator choices, never installer output.
:if ([/system/identity get name] != "mikrowarp-standard-lab") do={ :error "Not the dedicated lab" }
:if ([:len [/routing/table find where name="lab-warp"]] = 0) do={ /routing/table add name=lab-warp fib }
:if ([:len [/ip/route find where comment="R14 LAB ADMIN | WARP route"]] = 0) do={ /ip/route add dst-address=0.0.0.0/0 gateway=172.31.242.2 routing-table=lab-warp check-gateway=ping distance=1 comment="R14 LAB ADMIN | WARP route" }
:if ([:len [/ip/route find where comment="R14 LAB ADMIN | Chosen blackhole fallback"]] = 0) do={ /ip/route add blackhole dst-address=0.0.0.0/0 routing-table=lab-warp distance=254 comment="R14 LAB ADMIN | Chosen blackhole fallback" }
:if ([:len [/routing/rule find where comment="R14 LAB ADMIN | Private test client"]] = 0) do={ /routing/rule add src-address=192.168.88.10/32 action=lookup-only-in-table table=lab-warp comment="R14 LAB ADMIN | Private test client" }
:if ([:len [/ip/address find where address="198.18.14.1/24"]] = 0) do={ /ip/address add address=198.18.14.1/24 interface=lab-lan comment="R14 LAB ADMIN | Non-private source test subnet" }
:if ([:len [/routing/rule find where comment="R14 LAB ADMIN | Non-private test source"]] = 0) do={ /routing/rule add src-address=198.18.14.10/32 action=lookup-only-in-table table=lab-warp comment="R14 LAB ADMIN | Non-private test source" }
:put "LAB-ADMIN-POLICY-READY"
