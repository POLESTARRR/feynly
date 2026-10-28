# Economics

## Inflation

Inflation is a sustained increase in the general price level of goods and
services in an economy over time. When inflation rises, each unit of currency
buys fewer goods and services, purchasing power falls. It's typically
measured by tracking a basket of goods over time, such as the Consumer Price
Index (CPI). Moderate, predictable inflation (roughly 2% a year in many
developed economies) is generally considered healthy because it encourages
spending and investment over hoarding cash. Central banks (like the Federal
Reserve or RBI) try to control inflation primarily through interest rates:
raising rates makes borrowing more expensive, which cools spending and slows
price growth; cutting rates does the opposite. Inflation is different from a
single price increase, it specifically means a broad, sustained rise across
the economy, not just one product getting more expensive. Hyperinflation is
an extreme, out-of-control case, often above 50% a month, usually caused by a
government printing money far faster than the economy's actual output grows.

## Opportunity Cost

Opportunity cost is the value of the next-best alternative you give up when
you make a choice. It is not the sum of all foregone options, only the single
most valuable one you didn't take. Every choice has one, including choices
that involve no money: spending an hour studying has the opportunity cost of
whatever you'd otherwise have done with that hour. The concept matters because
the true cost of a decision is never just its price tag; it's the price plus
what you forfeited. Economists use it to explain why "free" things aren't
free, and why a business with a profitable factory might still be making a bad
decision if an even more profitable use of that capital exists.

# Biology

## Photosynthesis

Photosynthesis is the process plants, algae, and some bacteria use to convert
light energy into chemical energy stored in glucose. The overall reaction
takes in carbon dioxide and water, and, using energy captured from sunlight
by chlorophyll in the chloroplasts, produces glucose and releases oxygen as
a byproduct. It happens in two main stages. The light-dependent reactions
occur in the thylakoid membranes: light energy splits water molecules,
releasing oxygen, and generates ATP and NADPH (energy-carrying molecules).
The light-independent reactions (the Calvin cycle) occur in the stroma and
use that ATP and NADPH to fix carbon dioxide into glucose, this stage
doesn't directly need light, but depends on the products of the light
reactions. Photosynthesis is the foundational energy input for nearly all
food chains on Earth, and it's also the main reason atmospheric oxygen exists
at the levels it does.

## Natural Selection

Natural selection is the mechanism by which populations evolve over
generations. It requires three conditions: variation among individuals in a
population, heritability of that variation, and differential reproductive
success tied to it. Individuals whose inherited traits make them better suited
to their environment tend to survive and reproduce more, so those traits become
more common over generations. Crucially, natural selection acts on existing
variation, it does not create traits on demand, and individuals do not adapt
during their lifetime; populations change across generations. It is also not
inherently progressive: "fitness" means reproductive success in a specific
environment, so a trait that is advantageous in one environment can be harmful
in another when conditions shift.

# Computer Science

## TCP vs UDP

TCP (Transmission Control Protocol) and UDP (User Datagram Protocol) are the
two main transport-layer protocols used to send data over a network. TCP is
connection-oriented: before any data is sent, the two sides perform a
three-way handshake to establish a connection. TCP guarantees reliable,
ordered delivery, it retransmits lost packets and reorders out-of-sequence
ones, using acknowledgments and sequence numbers. This reliability adds
overhead and latency, which is why TCP is used for things where correctness
matters more than speed: web pages (HTTP), file transfers, email. UDP is
connectionless: it just fires packets ("datagrams") without a handshake, and
makes no guarantee they arrive, arrive in order, or arrive only once. That
makes it faster and lower-overhead than TCP, which is why it's used for video
calls, live streaming, and online gaming, a dropped or late packet is worse
for the experience than a slightly imperfect one. In short: TCP trades speed
for reliability; UDP trades reliability for speed.

## Big-O Notation

Big-O notation describes how an algorithm's running time or memory use grows
as the input size grows, ignoring constant factors and lower-order terms. It
describes an upper bound on growth rate, not actual speed: an O(n) algorithm
is not necessarily faster than an O(n²) one for small inputs, because Big-O
deliberately discards the constants that dominate at small scale. Common
classes, from best to worst: O(1) constant, O(log n) logarithmic, O(n) linear,
O(n log n), O(n²) quadratic, O(2ⁿ) exponential. The point of the notation is
to compare how algorithms *scale*, an O(n²) algorithm that's fine for 100
items may be unusable at 100,000. Big-O usually describes worst-case behavior
unless stated otherwise; average and best cases can differ substantially, as
with quicksort's O(n log n) average versus O(n²) worst case.
