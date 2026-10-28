import 'server-only';
import { getPublicLivingImageStore } from './public-images';
import { imageId } from './images';
export async function publicLivingGallery(source:string|null,articleId:string|null){
  if(source!=='machimoa_living'||!imageId(articleId))return [];
  return getPublicLivingImageStore().gallery(articleId);
}
