// Pure counterparts of ingest/location_evidence.py. The shared parity fixtures
// exercise both languages; this module never grants research/write authority.
export const locationKey=(value:string)=>value.normalize('NFKC').replace(/內/g,'내').replace(/((?:공원|전시관|박물관|센터))\s+(?:내|안)\s+/g,'$1 ').replace(/[\s·ㆍ,()[\]「」『』×-]/g,'');
const meeting='(?:만나는\\s*(?:장소|곳)|만남(?:의)?\\s*장소|모이는\\s*(?:장소|곳)|모임\\s*장소|집결\\s*(?:장소|지)|출발\\s*장소)';
const venue='(?:개최\\s*장소|운영\\s*장소|활동\\s*장소|장\\s*소)';
const facility=/^[가-힣A-Za-z0-9 ]+?(?:가드닝센터|지원센터|여가센터|힐링센터|문화센터|체험센터|전시관|체험관|과학관|박물관|도서관|플레이스|공원|창포원|광장|성당|전시실|센터|체험원|마을|궁|역)/;
export const facilityName=(place:string)=>place.trim().match(facility)?.[0].trim()||place.trim().replace(/\s+(?:앞|뒤)$/,'');
export function meetingPlaces(description:string):string[]{return [...description.matchAll(new RegExp('(?:^|\\n)[^\\p{L}\\p{N}\\n]*(?:\\d+[).]\\s*)?'+meeting+'\\s*(?:\\*{1,2}|__)?\\s*[:：]\\s*(?:\\*{1,2}|__)?([^\\n]+)','gu'))].map(m=>m[1].trim()).filter(Boolean);}
const qualifiers=(value:string)=>new Set(locationKey(value).match(/(?:\d+(?:번)?출구|[Bb]?\d+층|\d+(?:교육실|호실|실)|정문|후문|동문|서문|남문|북문)/g)||[]);
export function venueMatches(place:string,anchor:string):boolean{
 const p=locationKey(place),a=locationKey(anchor);if(a.includes(p))return true;
 const base=facilityName(place);if(locationKey(base).length<3||!a.includes(locationKey(base)))return false;
 const allowed=qualifiers(anchor);if([...qualifiers(place)].some(q=>!allowed.has(q)))return false;
 const tail=place.slice(base.length).trim();return !tail||/^\([^()]+\)$/.test(tail)&&a.includes(locationKey(tail));
}
export function sourceLink(title:string,description:string,place:string):[boolean,string]{
 const meetings=meetingPlaces(description);
 if(new RegExp(meeting).test(description)&&!meetings.length)return [false,'meeting_not_explicit'];
 if(meetings.length){if(new Set(meetings.map(locationKey)).size!==1)return [false,'meeting_multiple'];return [venueMatches(place,meetings[0]),'meeting'];}
 const locations=[...description.matchAll(new RegExp('(?:^|\\n)[^\\p{L}\\p{N}\\n]*(?:\\d+[).]\\s*)?'+venue+'\\s*[:：]\\s*([^\\n]+)','gu'))].map(m=>m[1]);
 if(locations.length)return [locations.some(line=>venueMatches(place,line)),'venue'];
 if(venueMatches(place,title))return [true,'title'];
 const lines=description.split('\n').filter(line=>venueMatches(place,line));if(!lines.length)return [false,'place_not_in_source'];
 const bad=/(?:기관\s*주소|문의처|주차장\s*(?:주소|위치)|오시는\s*길|수령\s*장소|운영\s*구간|이동\s*경로)\s*[:：]/;
 return [!lines.every(line=>bad.test(line)),'description'];
}
export function quoteLink(place:string,excerpt:string,province:string,district:string):boolean{
 if(['교육실','전시실','회의실','세미나실','체험실','센터','공원','광장','도서관','박물관','과학관','입구'].includes(facilityName(place)))return false;
 const regions=[...excerpt.matchAll(/(서울(?:특별시|시)?|경기(?:도)?|인천(?:광역시)?)\s+([가-힣]+(?:구|시|군))/g)];
 if(regions.some(m=>!m[1].startsWith(province)||m[2]!==district))return false;
 const exits=(v:string)=>new Set([...v.matchAll(/(\d+(?:\s*[,·/]\s*\d+)*)\s*번?\s*출구/g)].flatMap(m=>m[1].match(/\d+/g)||[]));
 const requested=exits(place),cited=exits(excerpt);if(requested.size&&cited.size&&[...requested].some(n=>!cited.has(n)))return false;
 const base=locationKey(facilityName(place));return base.length>=3&&locationKey(excerpt).includes(base)&&excerpt.includes(province)&&excerpt.includes(district);
}
export function sourceRegionConflict(description:string,place:string,province:string,district:string):boolean{
 const meetings=meetingPlaces(description),lines=meetings.length?meetings:description.split('\n').filter(line=>locationKey(line).includes(locationKey(facilityName(place)))&&!/기관\s*주소|문의처|주차장|수령\s*장소/.test(line));
 return lines.some(line=>[...line.matchAll(/(서울(?:특별시|시)?|경기(?:도)?|인천(?:광역시)?)\s+([가-힣]+(?:구|시|군))/g)].some(m=>!m[1].startsWith(province)||m[2]!==district));
}
