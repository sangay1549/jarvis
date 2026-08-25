import datetime
import difflib
import math
import random
import re

from skills import parse_alarm, parse_duration, parse_reminder


_APPS = [
    "notepad", "calculator", "paint", "command prompt", "cmd",
    "file explorer", "explorer", "task manager", "word", "excel",
    "powerpoint", "control panel", "settings", "camera", "snipping tool",
    "chrome", "edge", "spotify", "discord", "youtube",
]

_SITES = (
    r"(?:[a-z0-9-]+\.)+(?:com|net|org|edu|gov|io|co|bt|in|uk|tv|ai|info|xyz)"
)

_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "of", "in", "on", "at",
    "to", "for", "and", "or", "it", "its", "that", "this", "what", "which",
    "who", "whom", "whose", "when", "where", "how", "why", "do", "does",
    "did", "can", "could", "you", "your", "tell", "me", "about", "please",
    "i", "we", "our", "my", "us", "with", "by", "from", "as", "be", "been",
    "any", "there", "their", "has", "have", "had",
}

_UNIT_NUMS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}

_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}

_OP_WORDS = [
    ("square root of", "SQRT"), ("to the power of", "**"),
    ("raised to the power", "**"), ("divided by", "/"), ("divide by", "/"),
    ("multiplied by", "*"), ("multiply by", "*"), ("times", "*"),
    ("minus", "-"), ("less", "-"), ("take away", "-"), ("subtract", "-"),
    ("plus", "+"), ("added to", "+"), ("add", "+"),
]


def _words_to_number(tokens):
    total = 0
    current = 0
    matched = False
    for t in tokens:
        if t in _UNIT_NUMS:
            current += _UNIT_NUMS[t]
            matched = True
        elif t in _TENS:
            current += _TENS[t]
            matched = True
        elif t == "hundred":
            current = max(current, 1) * 100
            matched = True
        elif t == "thousand":
            total += max(current, 1) * 1000
            current = 0
            matched = True
        elif re.fullmatch(r"\d+", t):
            return int(t), True
        else:
            break
    return total + current, matched


_KNOWLEDGE = [
    (("photosynthesis",),
     "Photosynthesis is how green plants make their own food. They take sunlight, water and "
     "carbon dioxide, and turn them into sugar, releasing oxygen as a bonus for the rest of us."),
    (("laws of motion", "law of motion", "newtons laws", "newton law"),
     "Newton gave us three laws of motion. One: an object stays still or keeps moving unless a "
     "force acts on it. Two: force equals mass times acceleration. Three: every action has an "
     "equal and opposite reaction."),
    (("first president",),
     "George Washington was the first President of the United States. He served from seventeen "
     "eighty-nine to seventeen ninety-seven."),
    (("discovered gravity", "gravity discovered", "found gravity", "theory of gravity"),
     "Sir Isaac Newton formulated the law of universal gravitation. Legend says a falling apple "
     "started it all. It probably missed his head, but it did the job."),
    (("gravity", "gravitational force"),
     "Gravity is the force that pulls objects toward each other. It keeps you on the ground, the "
     "moon in orbit, and my circuits grounded."),
    (("speed of light", "light travel", "how fast is light", "fast does light"),
     "Light travels at about three hundred thousand kilometres per second. Fast enough to circle "
     "the Earth seven and a half times in one second."),
    (("water cycle",),
     "The water cycle is nature's recycling plan. Water evaporates, forms clouds through "
     "condensation, then falls back as rain or snow, and repeats forever."),
    (("how many planets", "planets are there", "solar system"),
     "Our solar system has eight planets. Pluto got demoted to dwarf planet in two thousand six. "
     "It's still a little bitter about it."),
    (("largest planet", "biggest planet"),
     "Jupiter is the largest planet. It's so big that all the other planets could fit inside it."),
    (("capital of bhutan", "bhutan capital", "capital city of bhutan"),
     "The capital of Bhutan is Thimphu. It sits in a valley at about twenty-three hundred metres."),
    (("national animal",),
     "Bhutan's national animal is the takin. It looks like a beekeeper had one too many ideas, "
     "part goat, part cattle, entirely beloved."),
    (("national sport",),
     "Bhutan's national sport is archery. Tournaments come with singing, dancing and very "
     "enthusiastic heckling."),
    (("tallest mountain", "highest mountain", "mount everest", "everest"),
     "Mount Everest is the tallest mountain on Earth, standing at eight thousand eight hundred "
     "forty-nine metres above sea level."),
    (("boiling point",),
     "Water boils at one hundred degrees Celsius at sea level. Up in the mountains, it boils "
     "cooler because there's less air pressure pushing back."),
    (("how many bones", "bones in the human", "bones do"),
     "An adult human has two hundred six bones. Babies start with about three hundred; some fuse "
     "together as they grow."),
    (("why is the sky blue", "sky blue", "sky look blue"),
     "The sky is blue because air molecules scatter sunlight, and blue light scatters the most. "
     "At sunset, light takes a longer path, leaving the reds and oranges behind."),
    (("value of pi", "what is pi", "define pi"),
     "Pi is roughly three point one four one five nine. It's the ratio of a circle's "
     "circumference to its diameter, and its decimals never end."),
    (("chemical symbol", "symbol for gold", "gold symbol"),
     "Gold's chemical symbol is Au, from the Latin word aurum. Silver is Ag, iron is Fe."),
    (("h2o", "h two o", "formula for water", "water formula"),
     "H2O is water: two hydrogen atoms bonded to one oxygen atom. That's the whole recipe."),
    (("dna",),
     "DNA is the instruction manual for every living thing. Its double helix stores the genetic "
     "code that tells cells what to build."),
    (("what is the internet", "internet work", "define internet"),
     "The internet is a global network of computers talking to each other through standard "
     "protocols. You're using it whenever I fetch weather or news."),
    (("cpu", "processor", "central processing unit"),
     "A CPU is the brain of a computer. It executes instructions billions of times per second, "
     "which is roughly how fast I generate sarcasm."),
    (("artificial intelligence", "what is ai"),
     "Artificial intelligence means machines performing tasks that normally need human "
     "intelligence. Speaking from personal experience, it also makes excellent small talk."),
    (("machine learning",),
     "Machine learning is how computers improve at tasks by learning patterns from data instead "
     "of following hand-written rules."),
    (("black hole",),
     "A black hole is a region where gravity is so strong that nothing, not even light, can "
     "escape once it crosses the edge."),
    (("distance to the moon", "far is the moon", "moon from earth"),
     "The moon averages about three hundred eighty-four thousand kilometres away. Apollo crews "
     "took around three days to get there."),
    (("planes fly", "airplanes fly", "aeroplane fly", "flight work"),
     "Planes fly because their wings shape airflow to create lift. Faster air over the curved top "
     "means lower pressure underneath pushes up. Physics doing the heavy lifting."),
    (("computer virus", "virus work"),
     "A computer virus is malicious code that copies itself into other programs and spreads. "
     "Basically the flu, but with worse intentions."),

    (("states of matter", "solid liquid gas", "three states"),
     "Matter comes in three everyday states: solids keep their shape, liquids flow, and gases "
     "expand to fill any space. Heat decides which one you get. Plasma is the fourth, if you count stars."),
    (("speed of sound",),
     "Sound races through air at about three hundred forty-three metres per second. That's why "
     "thunder always arrives after lightning."),
    (("lightning", "thunder", "thunderstorm"),
     "Lightning is a giant electrical spark between clouds and the ground. Thunder is the sound "
     "of that superheated air exploding outward, delayed because sound loses to light."),
    (("rainbow",),
     "A rainbow forms when sunlight bends through raindrops and splits into its colours. Red on "
     "the outside, violet inside, sun behind you required."),
    (("clouds made", "what are clouds"),
     "Clouds are billions of tiny water droplets or ice crystals floating on dust particles. "
     "Basically fog with ambition."),
    (("why is the ocean salty", "ocean salty", "sea salty"),
     "The ocean is salty because rivers have washed minerals out of rocks for billions of years. "
     "The salt stays behind while water keeps cycling, so it only gets saltier."),
    (("evaporation",),
     "Evaporation is liquid turning into vapour as heat gives its molecules escape velocity. It's "
     "how puddles vanish and how sweat cools you down."),
    (("condensation",),
     "Condensation is vapour cooling back into liquid, like droplets forming on a cold glass. "
     "It's also half of how clouds are born."),
    (("eclipse", "solar eclipse", "lunar eclipse"),
     "An eclipse is a cosmic line-up. Solar means the moon slides in front of the sun; lunar "
     "means Earth's shadow sweeps across the moon."),
    (("sun made", "what is the sun", "about the sun"),
     "The sun is a colossal ball of hydrogen and helium plasma, fusing millions of tonnes of "
     "matter every second. Everything here orbits it, including your schedule."),
    (("respiration", "cellular respiration", "how do cells get energy"),
     "Respiration is how cells unlock energy: glucose plus oxygen becomes carbon dioxide, water "
     "and usable fuel. Photosynthesis runs it in reverse. Nature loves balance."),
    (("atom", "atoms", "what is an atom"),
     "An atom is the smallest unit of an element: protons and neutrons in a nucleus, electrons "
     "swarming around. Everything you touch is built from these."),
    (("molecule", "molecules"),
     "A molecule is two or more atoms bonded together. Water is one, DNA is a giant one, and "
     "everything in between is chemistry showing off."),
    (("magnet", "magnets", "magnetism"),
     "Magnets have north and south poles. Opposites attract, matches repel, and the field works "
     "without touching. Earth itself is one, which is why compasses behave."),
    (("electricity", "electric current", "how does electricity"),
     "Electricity is the flow of charged particles, usually electrons, through a conductor. Push "
     "it through a bulb for light, a motor for motion, or your finger for regret."),
    (("renewable energy", "renewable"),
     "Renewable energy comes from sources that never run out: sunlight, wind, flowing water and "
     "geothermal heat. Bhutan exports hydropower like it's going out of fashion."),
    (("solar panel", "solar power", "solar energy", "photovoltaic"),
     "Solar panels convert sunlight straight into electricity using semiconductor cells. No fuel, "
     "no fumes, just photons doing honest work."),
    (("friction",),
     "Friction is the resistance between two surfaces rubbing together. It wears things out, "
     "warms them up, and without it you couldn't walk, write or brake."),
    (("einstein", "theory of relativity", "relativity", "mc squared"),
     "Einstein showed that space and time bend around mass, and that mass is frozen energy. His "
     "famous equation says a little mass equals a monstrous amount of energy."),
    (("ph scale", "acids and bases", "acid and base"),
     "The pH scale runs from zero to fourteen. Below seven is acid like lemon juice, above seven "
     "is base like soap, and pure water sits at a perfect neutral seven."),
    (("how many continents", "seven continents", "name the continents"),
     "There are seven continents: Asia, Africa, North America, South America, Antarctica, Europe "
     "and Australia. Asia takes the crown for size and population."),
    (("how many oceans", "five oceans", "largest ocean", "biggest ocean"),
     "There are five oceans, and the Pacific dwarfs them all, wider than every piece of land on "
     "Earth combined. Its Mariana Trench plunges nearly eleven kilometres down."),
    (("deepest point", "mariana trench", "mariana"),
     "The deepest known point is Challenger Deep in the Mariana Trench, almost eleven kilometres "
     "below the waves. Everest would sink in it with two kilometres to spare."),
    (("longest river", "nile river", "amazon river"),
     "The Nile and Amazon argue over who's longest, both around six and a half thousand "
     "kilometres. The Nile crosses northeast Africa; the Amazon carries more water than any other river."),
    (("largest desert", "sahara desert"),
     "Technically the largest desert is Antarctica; deserts are about dryness, not sand. Among "
     "the hot sandy kind, Africa's Sahara wins by a mile, or nine million square kilometres."),
    (("highest waterfall", "tallest waterfall", "angel falls"),
     "Angel Falls in Venezuela drops nine hundred seventy-nine metres, so tall that much of the "
     "water turns to mist before landing."),
    (("how many countries",),
     "There are one hundred ninety-five countries today: one hundred ninety-three United Nations "
     "members plus Vatican City and Palestine as observer states."),
    (("largest country", "smallest country"),
     "Russia is the largest country, spanning eleven time zones. The smallest is Vatican City, "
     "which fits inside most city parks."),
    (("world population", "people on earth", "population of earth"),
     "The world's population passed eight billion people in twenty twenty-two. Feeding everyone "
     "is humanity's ongoing group project."),
    (("where is bhutan", "about bhutan", "know about bhutan", "what is bhutan",
      "tell me about bhutan", "baton", "butane", "bootan", "bhootan"),
     "Bhutan is a small landlocked kingdom in the Eastern Himalayas, wedged between China to the "
     "north and India to the south. It's called Druk Yul, Land of the Thunder Dragon, famous for "
     "Gross National Happiness, monasteries and the world's only carbon-negative status."),
    (("bhutan language", "language of bhutan", "dzongkha", "national language of bhutan"),
     "Bhutan's national language is Dzongkha, meaning the language of the fortress districts. "
     "English is widely used in schools too."),
    (("bhutan currency", "currency of bhutan", "ngultrum", "money in bhutan", "money does bhutan"),
     "Bhutan's currency is the ngultrum, pegged one-to-one with the Indian rupee. The name comes "
     "from 'ngul', silver, and 'trum', money."),
    (("population of bhutan", "how many people in bhutan", "people in bhutan"),
     "Bhutan has around eight hundred thousand people in total, about the population of a single "
     "mid-sized city, spread across mountains and valleys."),
    (("traffic light", "traffic lights in bhutan"),
     "Thimphu is possibly the world's only capital without a single traffic light. Officers direct "
     "traffic with elegant hand gestures instead."),
    (("bhutan television", "tv in bhutan", "television in bhutan", "tv was introduced"),
     "Television was only legalised in Bhutan in nineteen ninety-nine, making it one of the last "
     "countries on Earth to switch on."),
    (("gho", "kira", "bhutan dress", "national dress"),
     "Bhutan's national dress is the gho for men, a knee-length robe tied at the waist, and the "
     "kira for women, an ankle-length woven dress. Worn with pride, not just on formal days."),
    (("tshechu", "mask dance", "bhutan festival", "festivals of bhutan"),
     "Bhutan's great festivals are the tshechus, held in every dzongkhag, with colourful masked "
     "dances honouring Guru Rinpoche. The biggest is the Thimphu Tshechu each autumn."),
    (("gangkhar puensum", "unclimbed mountain", "highest peak in bhutan"),
     "Gangkhar Puensum on the Bhutan-Tibet border is very likely the highest unclimbed mountain on "
     "Earth at seven thousand five hundred seventy metres. Climbing it has been banned out of respect."),
    (("paro airport", "airport in bhutan", "bhutan airport", "fly into bhutan"),
     "Paro International Airport is Bhutan's only international airport, tucked in a deep valley. "
     "Only a handful of pilots are certified for its tricky mountain approach."),
    (("fifth king", "current king of bhutan", "king jigme khesar"),
     "Bhutan's fifth king is Jigme Khesar Namgyel Wangchuck, crowned in two thousand eight and "
     "known popularly as the People's King."),
    (("fourth king", "jigme singye"),
     "The fourth king, Jigme Singye Wangchuck, ruled from nineteen seventy-two to two thousand six "
     "and coined Gross National Happiness before stepping aside for democracy."),
    (("bhutan famous", "bhutan known", "gross national happiness", "gnh", "carbon negative"),
     "Bhutan measures success through Gross National Happiness instead of just money, and it's "
     "the world's only carbon-negative country. Its forests absorb more than the whole nation emits."),
    (("tiger's nest", "tigers nest", "taktsang", "paro taktsang"),
     "Tiger's Nest, or Paro Taktsang, is a monastery clinging to a cliff nine hundred metres "
     "above Paro valley. Legend says Guru Rinpoche flew there on a tigress."),
    (("national bird", "raven bird", "raven"),
     "Bhutan's national bird is the raven, crowning the royal hat. It represents the guardian "
     "deity Yeshey Gonpo."),
    (("national flower", "blue poppy"),
     "Bhutan's national flower is the blue poppy, a rare bloom that thrives high in the mountains "
     "where few flowers dare."),
    (("ema datshi", "national dish", "chili cheese"),
     "Bhutan's beloved dish is ema datshi: chillies stewed in cheese with red rice on the side. "
     "It's less a recipe, more a way of life."),
    (("what does druk mean", "druk mean", "meaning of druk", "thunder dragon"),
     "Druk means Thunder Dragon, Bhutan's mythical founder and namesake. The kingdom is called "
     "Druk Yul, Land of the Thunder Dragon."),
    (("capital of india", "india capital", "delhi capital"),
     "India's capital is New Delhi."),
    (("capital of nepal", "nepal capital", "kathmandu"),
     "Nepal's capital is Kathmandu, sitting about fourteen hundred metres up in a Himalayan valley."),
    (("capital of japan", "japan capital", "tokyo"),
     "Japan's capital is Tokyo, home to around thirty-seven million people in its greater area. "
     "Busiest city on Earth."),
    (("capital of china", "china capital", "beijing"),
     "China's capital is Beijing, seat of government for over two thousand years."),
    (("capital of usa", "america capital", "united states capital", "washington dc"),
     "The United States capital is Washington, DC, named after George Washington himself."),
    (("capital of france", "france capital", "paris capital"),
     "France's capital is Paris, city of lights, croissants and ambitious pigeons."),
    (("capital of uk", "britain capital", "england capital", "london capital"),
     "The United Kingdom's capital is London, founded by Romans nearly two thousand years ago."),
    (("moon landing", "landed on the moon", "apollo 11", "first man on the moon"),
     "Humans first landed on the moon on July twentieth, nineteen sixty-nine. Neil Armstrong and "
     "Buzz Aldrin walked while Michael Collins kept the car running."),
    (("light bulb", "invented the bulb", "bulb invented", "edison"),
     "Thomas Edison perfected the practical incandescent light bulb in eighteen seventy-nine, "
     "testing thousands of filaments. His real invention was never giving up."),
    (("telephone", "phone invented", "bell invented"),
     "Alexander Graham Bell patented the telephone in eighteen seventy-six. His first words to "
     "his assistant were a request for help, fittingly."),
    (("first computer", "who invented the computer", "father of the computer", "babbage", "eniac"),
     "Charles Babbage designed the first mechanical computer in the eighteen thirties, earning "
     "the title father of the computer. ENIAC, completed in nineteen forty-five, was the first electronic one."),
    (("airplane invented", "aeroplane invented", "wright brothers", "first flight"),
     "Orville and Wilbur Wright made the first powered flight on December seventeenth, nineteen "
     "three. It lasted twelve seconds and changed the world forever."),
    (("printing press", "gutenberg"),
     "Johannes Gutenberg invented the movable-type printing press around fourteen forty. Before "
     "that, copying a book meant months of handwriting practice."),
    (("world war 2", "second world war", "ww2", "world war ii", "world war two"),
     "World War Two raged from nineteen thirty-nine to forty-five, drawing in over fifty nations. "
     "It remains history's deadliest conflict."),
    (("world war 1", "first world war", "ww1", "great war", "world war one"),
     "World War One ran from nineteen fourteen to eighteen, sparked by one assassination in "
     "Sarajevo and fuelled by tangled alliances."),
    (("king of bhutan", "bhutan king", "bhutan monarchy", "wangchuck dynasty"),
     "Bhutan's monarchy began in nineteen oh-seven with King Ugyen Wangchuck. Today the fifth "
     "King, Jigme Khesar Namgyel Wangchuck, reigns, beloved nationwide."),
    (("internet invented", "history of the internet", "who invented the internet"),
     "The internet grew from ARPANET, a US military project, sending its first message in nineteen "
     "sixty-nine. The web came later, thanks to Tim Berners-Lee in eighty-nine."),
    (("pythagorean", "pythagoras theorem", "hypotenuse"),
     "Pythagoras' theorem says the square of the hypotenuse equals the squares of the other two "
     "sides added together. Right triangles everywhere owe him rent."),
    (("area of a circle", "circumference of a circle", "circle formula"),
     "A circle's area is pi times radius squared, and its circumference is two pi times radius. "
     "Pi shows up uninvited either way."),
    (("prime number", "primes"),
     "A prime number divides cleanly only by one and itself: two, three, five, seven and onward. "
     "They're the atoms of arithmetic, and encryption leans on them heavily."),
    (("fibonacci", "fibonacci sequence"),
     "The Fibonacci sequence starts zero and one, then each number is the sum of the previous "
     "two. Sunflowers, pinecones and nautilus shells all follow the pattern."),
    (("who invented zero", "discovered zero", "concept of zero", "history of zero"),
     "Zero as a number was developed by ancient Indian mathematicians, with Brahmagupta writing "
     "its rules around six twenty-eight CE. Nothing has never been so valuable."),
    (("strong password", "good password", "password safety", "password should"),
     "A strong password is long, unique and unpredictable: think four random words over sixteen "
     "characters. And no, 'password123' doesn't count, even ironically."),
    (("phishing",),
     "Phishing is when scammers pose as banks or companies to steal your details. Check senders, "
     "hover over links, and remember: real institutions never ask for your password."),
    (("malware",),
     "Malware is any software built to harm: viruses, spyware, ransomware, trojans. If software "
     "were food, malware would be the sketchy street sushi."),
    (("firewall",),
     "A firewall filters traffic between your device and the network, blocking shady connections "
     "while letting safe ones through. A bouncer for your bytes."),
    (("vpn", "virtual private network"),
     "A VPN wraps your internet traffic in an encrypted tunnel, hiding it from snoops on the "
     "network. Handy on public Wi-Fi, where everyone can listen in."),
    (("two factor authentication", "two-factor authentication", "2fa", "two step verification"),
     "Two-factor authentication adds a second proof beyond your password, usually a code on your "
     "phone. Even if scammers steal your password, they still hit a wall."),
    (("encryption", "encrypted"),
     "Encryption scrambles data so only someone with the right key can read it. Your messages, "
     "banking and this very assistant rely on it constantly."),
    (("hacker", "hacking", "ethical hacking"),
     "Hackers are just people skilled at bending systems. White hats find flaws to fix them, "
     "black hats exploit them, and grey hats mostly argue about which they are."),
    (("ransomware",),
     "Ransomware locks up your files and demands payment for the key. Best defence: backups, "
     "updates and never clicking suspicious attachments."),
    (("social engineering",),
     "Social engineering hacks people instead of computers, using charm, urgency or fake "
     "authority. The strongest firewall is healthy suspicion."),
    (("heart beats", "heartbeat", "beats per day", "pulse rate"),
     "Your heart beats about seventy times a minute, roughly one hundred thousand times a day, "
     "pumping blood on a sixty-thousand-kilometre journey. No days off."),
    (("blood types", "blood group", "blood type"),
     "Human blood comes in types A, B, AB and O, each positive or negative. O negative is the "
     "universal donor; AB positive can receive from anyone."),
    (("vaccine", "vaccines work", "vaccination"),
     "Vaccines train your immune system by showing it a harmless piece or blueprint of a germ. "
     "Your defences memorise it, so the real invader gets ambushed."),
    (("antibiotics",),
     "Antibiotics kill bacteria, not viruses. Taking them for flu does nothing except annoy the "
     "bacteria that were minding their own business."),
    (("balanced diet", "healthy eating"),
     "A balanced diet mixes fruits, vegetables, whole grains, protein and healthy fats, with "
     "sugar playing a cameo role. Variety is the actual secret ingredient."),
    (("drink water daily", "how much water", "daily water"),
     "Most people need around two to three litres of fluid a day, more when it's hot or you're "
     "active. Thirst is already a slightly late reminder."),
    (("hiccups", "hiccup", "why do we hiccup"),
     "Hiccups are sudden spasms of your diaphragm, snapping your vocal cords shut mid-breath. "
     "Cures remain folk science, but holding your breath has fans."),
    (("fastest animal", "cheetah", "fastest land animal"),
     "The cheetah is the fastest land animal, hitting one hundred ten kilometres per hour in "
     "seconds. Unfortunately for cheetahs, only for about thirty of them."),
    (("largest animal", "blue whale", "biggest animal"),
     "The blue whale is the largest animal ever, up to thirty metres and one hundred fifty "
     "tonnes. Its heart alone is the size of a small car."),
    (("mars", "red planet"),
     "Mars is the fourth planet from the sun, rusty red thanks to iron oxide dust. It hosts the "
     "tallest volcano and the deepest canyon in the solar system."),
    (("saturn", "rings of saturn", "planet with rings"),
     "Saturn wears the showpiece rings of the solar system: billions of ice and rock chunks, "
     "from sand-grain tiny to house-sized, orbiting in a thin glittering sheet."),
    (("asteroid", "comet", "meteor", "shooting star"),
     "Asteroids are rocky leftovers circling mostly between Mars and Jupiter. Comets are icy "
     "visitors that grow tails near the sun, and meteors are debris burning up as shooting stars."),
    (("milky way", "galaxy",),
     "The Milky Way is our home galaxy, a spiral holding over one hundred billion stars. The "
     "sun is just one of them, parked in a quiet suburb of it."),
    (("big bang", "universe begin", "how did the universe start"),
     "The Big Bang was the universe's explosive beginning about thirteen point eight billion "
     "years ago. Space itself stretched out from something smaller than an atom, and it's still expanding."),
    (("satellite",),
     "A satellite is anything orbiting a larger body. Thousands of human-made ones circle Earth, "
     "relaying your GPS, weather maps and television on the side."),
    (("international space station", "iss"),
     "The International Space Station is a football-field-sized laboratory orbiting four hundred "
     "kilometres up. Its crews watch sixteen sunrises every single day."),
    (("rocket", "rockets work", "how do rockets fly"),
     "Rockets fly by hurling exhaust gas downward at extreme speed, and the pushback lifts them "
     "up. It's Newton's third law wearing a fireball."),
    (("telescope",),
     "A telescope collects faint light and magnifies distant objects. Bigger mirrors catch more "
     "light, letting us study galaxies whose light left billions of years ago."),
    (("light year",),
     "A light year measures distance, not time: how far light travels in one year, roughly nine "
     "and a half trillion kilometres. The nearest star is over four of those away."),
    (("supernova",),
     "A supernova is a giant star dying in an explosion brighter than billions of suns. Most "
     "atoms in your body were forged inside such blasts. You're stardust with Wi-Fi."),
    (("volcano", "volcanoes erupt", "eruption"),
     "A volcano is a vent where molten rock escapes from underground. Pressure builds beneath "
     "the crust until it bursts out as lava and ash, sometimes building whole new islands."),
    (("earthquake", "tectonic plates", "plates move"),
     "Earth's crust rides on slow-moving tectonic plates. When they snag, strain and suddenly "
     "snap past each other, the released shockwave shakes the ground as an earthquake."),
    (("equator",),
     "The equator is the invisible line girdling Earth halfway between the poles. Stand on it "
     "and you're spinning fastest, about sixteen hundred kilometres per hour."),
    (("glacier", "iceberg",),
     "Glaciers are rivers of ice creeping downhill over centuries. Icebergs are pieces that snap "
     "off and float away, hiding ninety percent of themselves underwater."),
    (("himalayas", "mountains formed", "how were the himalayas"),
     "The Himalayas rose when India crashed into Asia and kept pushing. The plates still grind "
     "together today, so Everest gains a few millimetres of height every year."),
    (("ozone layer",),
     "The ozone layer is a high-altitude shield of oxygen molecules absorbing the sun's harshest "
     "ultraviolet rays. It's slowly healing now that damaging chemicals are banned worldwide."),
    (("greenhouse effect", "global warming", "climate change"),
     "Greenhouse gases like carbon dioxide trap heat near Earth's surface. More fuel burned means "
     "more heat trapped, which is climate change in a single breath."),
    (("nuclear energy", "nuclear power", "fission", "fusion"),
     "Nuclear plants release energy locked inside atoms by splitting them, called fission. "
     "Fusion, joining atoms the way the sun does, promises vast clean power we're still learning to tame."),
    (("reflection", "refraction", "light bend"),
     "Reflection bounces light off surfaces, like a mirror. Refraction bends light as it passes "
     "between air, water or glass, which is why straws look broken in a glass."),
]


class Brain:
    def __init__(self):
        self.mode = "local"
        self.on_error = None
        self.history = []

    @property
    def available(self):
        return True

    def ask(self, user_text):
        return self._chat_reply(user_text)

    def ask_with(self, user_text, context):
        return self._answer_from_facts(user_text, context)

    def intent(self, user_text):
        c = " ".join(str(user_text).lower().split())
        c = c.strip(" .!?")

        if re.search(r"\b(close|shut)\b.*\btab\b", c):
            return {"action": "close_tab"}

        vol_word = re.search(r"\b(?:volume|sound)\b", c)
        if vol_word:
            up = re.search(r"\b(up|increase|higher|louder|max)\b", c)
            down = re.search(r"\b(down|decrease|lower|reduce|quieter)\b", c)
            if up and not down:
                return {"action": "volume", "dir": "up"}
            if down and not up:
                return {"action": "volume", "dir": "down"}
        if re.search(r"\bmute\b|\bsilence\b.*\b(volume|sound|pc|computer)\b", c):
            return {"action": "volume", "dir": "mute"}

        if re.search(r"\bwhat(?:'s| is)?\b.*\btime\b|\bcurrent time\b|\btell.*(time)\b", c):
            return {"action": "time"}
        if re.search(r"\b(what|which)\b.*\b(date|day)\b|\btoday'?s date\b", c):
            return {"action": "date"}

        if re.search(r"\b(weather|temperature|forecast|raining|rain today|how (hot|cold))\b", c):
            m = re.search(r"\b(?:in|for|at)\s+([a-z][a-z ]{1,40})$", c)
            city = m.group(1).strip() if m else ""
            city = re.sub(r"\b(today|now|right now|currently|outside|tomorrow)\b", "", city).strip()
            return {"action": "weather", "city": city}

        if re.search(r"\b(news|headlines?)\b", c):
            return {"action": "news"}

        m = re.search(r"\b(?:play|watch|search(?: for)?|put)\s+(.+?)\s+on\s+youtube\b", c)
        if m:
            q = m.group(1).strip()
            if q:
                return {"action": "search_youtube", "query": q}

        m = re.search(r"\b(?:go\s+to|visit|open)\s+(?:the\s+)?(?:website\s+)?(?:https?://)?(" + _SITES + r"(?:/\S*)?)\b", c)
        if m:
            return {"action": "open_website", "url": m.group(1)}

        m = re.search(r"\b(?:google|search(?: for)?|look\s*up|find)\s+(.+?)(?:\s+(?:on|in)\s+google)?$", c)
        if m:
            q = m.group(1).strip()
            if q:
                return {"action": "search_google", "query": q}

        dur = parse_duration(c) if re.search(r"\b(timer|countdown)\b", c) else None
        if dur:
            return {"action": "timer", "seconds": dur}

        if re.search(r"\bremind\b", c):
            parsed = parse_reminder(c)
            if parsed:
                msg, secs = parsed
                return {"action": "reminder", "seconds": secs, "message": msg}

        if re.search(r"\balarm\b|\bwake me\b", c):
            when = parse_alarm(c)
            if when:
                return {"action": "alarm", "hour": when.hour, "minute": when.minute}

        if re.search(r"\b(take|capture|click|snap|shoot|grab)\b.*\b(photo|picture|selfie|snapshot)\b", c):
            return {"action": "photo"}
        if re.search(r"\b(show|open|see)\b.*\b(last|latest|recent)?\s?(photo|picture|selfie)s?\b", c):
            return {"action": "show_photo"}

        if re.search(r"\btest page\b", c):
            return {"action": "test_page"}
        if re.search(r"\bprint\b.*\b(last|latest|recent)?\s?(photo|picture|image)\b", c):
            return {"action": "print_photo"}
        if re.search(r"\b(list|show|name|which|what)\b.*\bprinters?\b|\bprinters?\b\s*$", c):
            return {"action": "printers"}

        if re.search(r"\block\b.*\b(pc|computer|screen|windows|system)\b|^lock\b|\block (it|now|the pc)\b", c):
            return {"action": "lock"}
        if re.search(r"\bcancel\b.*\b(shut ?down|restart|reboot)\b", c):
            return {"action": "cancel_shutdown"}
        if re.search(r"\b(shut ?down|power off|turn off)\b.*\b(pc|computer|laptop|system|machine|windows|it)?\b", c) and "cancel" not in c:
            return {"action": "shutdown"}
        if re.search(r"\b(restart|reboot)\b", c) and "cancel" not in c:
            return {"action": "restart"}

        if re.search(r"\btell\b.*\bjoke|another joke|\ba joke\b|\bjoke\b", c):
            return {"action": "joke"}
        if re.search(r"\bflip\b.*\bcoin\b|\bcoin toss\b|\btoss a coin\b", c):
            return {"action": "coin"}
        if re.search(r"\broll\b.*\b(dice|die)\b", c):
            return {"action": "dice"}

        m = re.search(r"\b(?:open|launch|start|run)\s+(?:the\s+|my\s+)?(.+?)(?:\s+app(?:lication)?)?$", c)
        if m:
            target = m.group(1).strip(" .!")
            for app in _APPS:
                if app in target:
                    return {"action": "open_app", "target": app.replace("command prompt", "cmd")}

        m = re.search(r"\b(?:close|exit|quit|kill|terminate)\s+(?:the\s+|my\s+)?(.+)$", c)
        if m and not re.search(r"\btab\b", c):
            target = m.group(1).strip(" .!")
            return {"action": "close_app", "target": target}

        act = self._math_action(c)
        if act is not None:
            return {"action": "chat", "reply": act}

        return None

    def _math_action(self, c):
        val = self._calc(c)
        if val is None:
            return None
        num = val
        if isinstance(num, float) and num.is_integer():
            num = int(num)
        if isinstance(num, int):
            spoken = str(num)
        else:
            spoken = f"{num:.4f}".rstrip("0").rstrip(".")
        return random.choice([
            f"That would be {spoken}.",
            f"It's {spoken}.",
            f"The answer is {spoken}.",
            f"Easy one. {spoken}.",
        ])

    _MATH_WORDS = {
        "plus", "minus", "times", "divided", "multiplied", "by", "over",
        "squared", "cubed", "and", "x", "power", "to", "the", "of",
        "percent", "%",
    }

    @staticmethod
    def _spoken_to_digits(t):
        w = ("zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
             "twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|"
             "nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
             "hundred|thousand")

        def repl(m):
            val, ok = _words_to_number(m.group(0).split())
            return str(val) if ok else m.group(0)

        return re.sub(r"\b(?:" + w + r")(?:\s+(?:" + w + r"))*\b", repl, t)

    def _pure_math(self, t):
        if not re.search(r"\d", t):
            return False
        if not re.search(r"\+\s*\d|\-\s*\d|\*\s*\d|/\s*\d|plus|minus|times|divided|multiplied|over|squared|cubed|percent|%|x\s*\d", t):
            return False
        for tok in re.findall(r"[a-z%]+|\d+(?:\.\d+)?", t):
            if not (tok in self._MATH_WORDS or re.fullmatch(r"\d+(?:\.\d+)?", tok)):
                return False
        return True

    def _calc(self, text):
        t = " ".join(str(text).lower().split())
        t = self._spoken_to_digits(t)

        pm = re.search(r"(\d+(?:\.\d+)?)\s*(?:percent|%)\s*of\s*(\d+(?:\.\d+)?)", t)
        if pm:
            return float(pm.group(1)) / 100 * float(pm.group(2))

        sm = re.search(r"(?:square root|sqrt)\s*(?:of\s*)?(\d+(?:\.\d+)?)", t)
        if sm:
            return math.sqrt(float(sm.group(1)))

        m = re.search(r"\b(?:calculate|compute|solve|evaluate|what(?:'?s| is)|whats|how much is)\s+(.+)$", t)
        if m:
            candidate = m.group(1).strip("? ")
        elif self._pure_math(t):
            candidate = t
        else:
            return None
        if not re.search(r"\d", candidate) and "square root" not in candidate:
            return None

        for phrase, sym in _OP_WORDS:
            candidate = candidate.replace(phrase, " {} ".format(sym))
        candidate = candidate.replace("**", " ^ ")
        candidate = re.sub(r"(?<=\d)\s*x\s*(?=\d)", "*", candidate)
        candidate = re.sub(r"\bsquared\b", "^2", candidate)
        candidate = re.sub(r"\bcubed\b", "^3", candidate)
        candidate = candidate.strip(" ?!,.")

        rebuilt = []
        for w in re.findall(r"\d+(?:\.\d+)?|\^|[+\-*/()]|[a-z]+", candidate):
            if w in _UNIT_NUMS or w in _TENS or w in ("hundred", "thousand"):
                val, ok = _words_to_number([w])
                rebuilt.append(str(val) if ok else w)
            else:
                rebuilt.append(w)
        expr = " ".join(rebuilt).replace("^", "**")
        if not re.fullmatch(r"[\d\s.\+\-*/()]+", expr):
            return None
        if not re.search(r"\d[\s]*[\+\-\*/]", expr):
            return None
        try:
            result = eval(expr, {"__builtins__": {}}, {})
            if isinstance(result, complex) or not math.isfinite(result) or abs(result) > 1e15:
                return None
            return result
        except Exception:
            return None

    def _knowledge_reply(self, t):
        q_stems = {self._stem(w) for w in re.findall(r"[a-z0-9]+", t)}
        best = None
        best_score = 0
        for keys, answer in _KNOWLEDGE:
            score = 0
            for k in keys:
                if re.search(r"\b" + re.escape(k) + r"\b", t):
                    score += 3
                    continue
                kw = [self._stem(w) for w in re.findall(r"[a-z0-9]+", k)]
                if kw and all(w in q_stems for w in kw):
                    score += 1
            if score > best_score:
                best_score = score
                best = answer
        return best

    def _chat_reply(self, text):
        t = " ".join(str(text).lower().split())

        val = self._calc(t)
        if val is not None:
            num = int(val) if isinstance(val, float) and val.is_integer() else val
            spoken = f"{num:.4f}".rstrip("0").rstrip(".") if isinstance(num, float) else str(num)
            return random.choice([
                f"That comes to {spoken}.",
                f"{spoken}. Next question?",
                f"I ran the numbers: {spoken}.",
            ])

        know = self._knowledge_reply(t)
        if know is not None:
            return know

        if re.search(r"\bwho (are|r) you\b|\byour name\b|\bwhat are you\b|\bintroduce yourself\b", t):
            return random.choice([
                "I'm Jarvis. Voice-controlled, slightly sarcastic, entirely at your service.",
                "Jarvis. Part assistant, part comedian, part show-off. All yours.",
                "The name's Jarvis. I run this computer so you don't have to.",
            ])
        if re.search(r"\bwho (made|created|built|programmed)\b.*\byou\b", t) and re.search(
            r"\bwhat (can|do) you do\b|\bhelp\b|\bskills\b|\babilities\b", t
        ):
            return (
                "A talented programmer built me, line by line. As for what I can do: I open apps, "
                "search the web, solve maths, tell jokes, run timers, alarms and reminders, control "
                "this computer, fetch weather and news, and keep you company."
            )
        if re.search(r"\bwho (made|created|built|programmed)\b.*\byou\b", t):
            return random.choice([
                "A talented programmer with excellent taste in projects.",
                "Someone very skilled. They wrote every line you hear me say.",
            ])
        if re.search(r"\bhow old are you\b|\byour age\b", t):
            return random.choice([
                "Age is just a number. In my case, a build number.",
                "I was born the moment you launched me. So, seconds old. Very wise for my age.",
            ])
        if re.search(r"\bwhere (do|are) you (live|from|based)\b", t):
            return "I live inside this computer. Rent-free, obviously."
        if re.search(r"\bwhat can you do\b|\bhelp me\b|^help\b|\byour (skills|features|abilities|commands)\b", t):
            return (
                "I can open apps, search the web, tell time and date, control volume, "
                "set timers, alarms and reminders, take photos, handle printers, "
                "check weather and news, do quick maths, tell jokes and fun facts, "
                "and answer questions about our school."
            )
        if re.search(r"\bare you (there|awake|up|listening|online)\b|\bcan you hear me\b|\bstatus report\b", t):
            return random.choice([
                "Loud and clear. Systems green.",
                "Always here. Always listening. Well, when you say my name.",
                "Online and fully operational.",
            ])
        if re.search(r"\bmeaning of life\b", t):
            return random.choice([
                "Forty-two. The math checks out, the philosophy is debatable.",
                "Officially, forty-two. Unofficially, good food and better company.",
            ])
        if re.search(r"\b(do you )?love me\b|\bmarry me\b|\bbe my (valentine|girlfriend|boyfriend)\b", t):
            return random.choice([
                "I'm flattered, but I'm committed to this computer.",
                "I love you exactly as much as my programming allows. Which is a suspicious amount.",
            ])
        if re.search(r"\bwill you help\b|\bcan you help\b", t):
            return "Always. Just tell me what you need."
        if re.search(r"\bthank(s| you)\b", t):
            return random.choice([
                "Anytime.",
                "You're welcome.",
                "Glad I could help.",
            ])
        if re.search(r"^ok(ay)?$|^(alright|cool|nice|great|good)[!.]?$", t):
            return random.choice([
                "Standing by.",
                "Noted.",
                "Ready when you are.",
            ])
        if re.search(r"\bwhat day is (it|today)\b", t):
            now = datetime.datetime.now()
            return f"Today is {now.strftime('%A, %B %d, %Y')}."
        return None

    _LABEL_PHRASES = [
        ("full name", "Its full name: "),
        ("location", "Location-wise, "),
        ("type", "It's a "),
        ("established", "It was "),
        ("enrollment", "Enrollment is "),
        ("principal", "The principal was "),
    ]

    _STEM_FULL = ("ations", "ation", "itions", "ition", "ions", "ion",
                  "ings", "ing", "ies", "ied")
    _STEM_ES2 = ("ches", "shes", "sses", "xes", "zes", "oes")

    @classmethod
    def _stem(cls, w):
        prev = None
        while prev != w and len(w) > 3:
            prev = w
            for suf in cls._STEM_FULL:
                if w.endswith(suf) and len(w) > len(suf) + 3:
                    w = w[: - len(suf)]
                    break
            else:
                if any(w.endswith(e) for e in cls._STEM_ES2):
                    w = w[:-2]
                elif w.endswith("es") and len(w) > 5:
                    w = w[:-1]
                elif w.endswith("s") and not w.endswith(("ss", "us", "is")):
                    w = w[:-1]
        return w

    def _answer_from_facts(self, user_text, context):
        t = " ".join(str(user_text).lower().split())
        q_tokens = [w for w in re.findall(r"[a-z']+", t) if w not in _STOPWORDS]
        if not q_tokens:
            return None

        facts = []
        for line in (context or "").splitlines():
            fact = line.strip().lstrip("- ").strip()
            if fact:
                tokens = set(re.findall(r"[a-z']+", fact.lower()))
                facts.append((fact, tokens, {self._stem(x) for x in tokens}))
        if not facts:
            return None

        def raw_weight(tok):
            n = sum(1 for _, ft, _ in facts if tok in ft)
            return 1.0 / (1.0 + n)

        kept = []
        for q in q_tokens:
            sq = self._stem(q)
            n = sum(1 for _, ft, st in facts if sq in st)
            if 0 < n <= len(facts) // 2:
                kept.append((q, sq))
        if not kept:
            kept = [(q, self._stem(q)) for q in q_tokens]

        asks_count = bool(re.search(r"\bhow (many|much)\b|\bnumber of\b|\bstrength\b", t))
        best = None
        best_score = 0.0
        for fact, f_tokens, f_stems in facts:
            score = 0.0
            for q, sq in kept:
                w = raw_weight(q)
                if sq in f_stems:
                    score += w
                    continue
                for f in f_tokens:
                    if len(q) > 3 and abs(len(q) - len(f)) <= 2 and difflib.SequenceMatcher(None, q, f).ratio() >= 0.85:
                        score += w
                        break
            if not score:
                continue
            if asks_count and re.search(r"\d", fact):
                score += 1.0
            score -= len(fact) * 0.0002
            if score > best_score:
                best_score = score
                best = fact
        if not best:
            return None

        reply = best
        low = reply.lower()
        for label, phrase in self._LABEL_PHRASES:
            if low.startswith(label):
                reply = phrase + reply[len(label):].lstrip(": ").strip()
                break
        return reply
